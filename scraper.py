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
    
    diretorio_atual = os.path.dirname(os.path.abs
