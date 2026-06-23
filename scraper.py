import json
import os
import requests
from bs4 import BeautifulSoup
from google import genai
from pydantic import BaseModel, Field
import typing
from datetime import datetime

# Estrutura esperada de saída usando Pydantic para forçar as chaves corretas no JSON
class EditalOutput(BaseModel):
    Nomes: str
    Link: str
    Resumo: str
    Prazo_de_inscricao: str = Field(alias="Prazo de inscrição")
    Valor_do_edital: str = Field(alias="Valor do edital")
    Periodo_de_execucao_do_projeto: str = Field(alias="Período de execução do projeto")
    is_valid_edital: bool

def obter_texto_pagina(url: str) -> typing.Tuple[str, str]:
    """Faz o download da página html e extrai apenas o texto visível. Retorna (texto, erro_mensagem)."""
    print(f"[{url}] Baixando página...")
    try:
        # Header genérico para evitar bloqueios triviais
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        }
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Remove tags indesejadas que não nos ajudam (scripts, estilos, cabeçalhos de navegação)
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'noscript']):
            tag.decompose()
            
        texto = soup.get_text(separator=' ', strip=True)
        return texto[:20000], ""
    except requests.exceptions.Timeout:
        return "", "Tempo limite atingido (15s)"
    except Exception as e:
        return "", str(e)

def analisar_edital_com_gemini(texto_pagina: str, url: str) -> typing.Optional[dict]:
    """Envia o texto limpo ao Gemini e exige a estrutura JSON de resposta."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Erro: A variável de ambiente GEMINI_API_KEY não foi encontrada.")
        return None
        
    client = genai.Client(api_key=api_key)
    
    print(f"[{url}] Analisando conteúdo com o modelo Gemini...")
    
    prompt = f"""
    Analise o texto abaixo extraído de uma página da web. 
    Sua única tarefa é determinar se este é um EDITAL ABERTO DE APOIO FINANCEIRO / PROJETO e extrair os dados.
    Escreva um resumo de exatamente DUAS frases falando sobre o foco do edital.
    Extraia o valor do edital e o período de execução máximo. Se essas informações não estiverem claras, retorne "Não especificado".
    Para a data de inscrição, use explicitamente formatos como "DD de Mês de AAAA", ou retorne "Não especificado" / "Inscrições Contínuas".
    Se esta página não tratar de um edital ativo válido para captação de recursos/projetos, marque is_valid_edital como false.

    Se o texto fornecido para análise estiver vazio, contiver erros de rede (como 403 Forbidden ou 503) ou não contiver detalhes específicos de editais de fomento abertos e ativos, retorne obrigatoriamente 'is_valid_edital': false. É proibido inventar informações que não estejam explicitamente escritas no texto fornecido.
    
    TEXTO DA PÁGINA:
    {texto_pagina}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'response_schema': EditalOutput,
            },
        )
        
        resultado = json.loads(response.text)
        resultado["Link"] = url # Vamos garantir o link original independente da resposta da IA
        return resultado
    except Exception as e:
        print(f"[{url}] Erro na analise com Gemini: {e}")
        return None

def run_scraper():
    print("Iniciando fase de raspagem...\n")
    
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo_json = os.path.join(diretorio_atual, 'editais.json')
    caminho_arquivo_urls = os.path.join(diretorio_atual, 'urls.txt')
    
    # Valida se o arquivo urls.txt existe
    if not os.path.exists(caminho_arquivo_urls):
        print(f"Erro: O arquivo {caminho_arquivo_urls} não foi encontrado.")
        return

    # Lê as URLs do arquivo
    with open(caminho_arquivo_urls, 'r', encoding='utf-8') as f:
        urls_para_analisar = [linha.strip() for linha in f if linha.strip() and not linha.startswith('#')]

    if not urls_para_analisar:
        print("Nenhuma URL encontrada em urls.txt.")
        return
    
    # 1. Carrega dados existentes
    editais_existentes = []
    if os.path.exists(caminho_arquivo_json):
        with open(caminho_arquivo_json, 'r', encoding='utf-8') as f:
            try:
                editais_existentes = json.load(f)
            except json.JSONDecodeError:
                print("Arquivo json vazio ou inválido. Criando nova estrutura.")

    # Usamos o link como chave única para evitar duplicados
    links_existentes = {edital.get("Link") for edital in editais_existentes}
    novos_editais = []
    
    # Estrutura do status
    status_detalhes = []
    stats = {"total_sites": len(urls_para_analisar), "sucessos": 0, "recusados": 0, "erros": 0}
    
    for url in urls_para_analisar:
        texto, erro_msg = obter_texto_pagina(url)
        
        if erro_msg:
            print(f"[{url}] ⚠️ Erro: {erro_msg}")
            stats["erros"] += 1
            status_detalhes.append({"url": url, "status": "Erro", "info": erro_msg})
            continue

        if url in links_existentes:
            print(f"[{url}] Já existe.")
            # Para manter o status completo, vou tratar como "Sucesso (ignorado)"
            stats["sucessos"] += 1
            status_detalhes.append({"url": url, "status": "Sucesso", "info": "Já monitorado"})
            continue
            
        dados = analisar_edital_com_gemini(texto, url)
        
        if dados:
            if dados.get("is_valid_edital"):
                print(f"[{url}] ✅ Sucesso!")
                stats["sucessos"] += 1
                edital_final = {k: v for k, v in dados.items() if k != "is_valid_edital"}
                novos_editais.append(edital_final)
                status_detalhes.append({"url": url, "status": "Sucesso", "info": dados.get("Nomes")})
            else:
                print(f"[{url}] ❌ Recusado!")
                stats["recusados"] += 1
                status_detalhes.append({"url": url, "status": "Recusado", "info": "Nenhum edital ativo"})
        else:
            stats["erros"] += 1
            status_detalhes.append({"url": url, "status": "Erro", "info": "Falha na análise"})

    # Salvar editais
    if novos_editais:
        lista_atualizada = novos_editais + editais_existentes
        os.makedirs(os.path.dirname(caminho_arquivo_json), exist_ok=True)
        with open(caminho_arquivo_json, 'w', encoding='utf-8') as f:
            json.dump(lista_atualizada, f, ensure_ascii=False, indent=4)
            
    # Salvar status
    caminho_arquivo_status = os.path.join(diretorio_atual, 'status.json')
    status_data = {
        "ultima_atualizacao": datetime.now().strftime('%d/%m/%Y às %H:%M'),
        "resumo": stats,
        "detalhes": status_detalhes
    }
    with open(caminho_arquivo_status, 'w', encoding='utf-8') as f:
        json.dump(status_data, f, ensure_ascii=False, indent=4)
            
    print(f"\nConcluído! Atualizado em {caminho_arquivo_status}")

if __name__ == "__main__":
    run_scraper()
