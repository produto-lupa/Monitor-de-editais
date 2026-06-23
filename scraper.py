import json, os, requests, typing
from bs4 import BeautifulSoup
from google import genai
from pydantic import BaseModel, Field
from datetime import datetime

class EditalOutput(BaseModel):
    Nomes: str
    Link: str
    Resumo: str
    Prazo_de_inscricao: str = Field(alias="Prazo de inscrição")
    Valor_do_edital: str = Field(alias="Valor do edital")
    Periodo_de_execucao_do_projeto: str = Field(alias="Período de execução do projeto")
    is_valid_edital: bool

def obter_texto_pagina(url: str) -> typing.Tuple[str, str]:
    print(f"[{url}] Baixando página...")
    try:
        hd = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=hd, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'noscript']):
            tag.decompose()
        return soup.get_text(separator=' ', strip=True)[:20000], ""
    except requests.exceptions.Timeout:
        return "", "Tempo limite excedido"
    except Exception as e:
        return "", str(e)

def analisar_edital_com_gemini(texto: str, url: str) -> typing.Optional[dict]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Erro: GEMINI_API_KEY ausente.")
        return None
    client = genai.Client(api_key=api_key)
    print(f"[{url}] Analisando com Gemini...")
    
    # Prompt detalhado escrito em linhas curtas para evitar cortes físicos de texto
    prompt = f"""
    Sua única tarefa é ler o texto abaixo de uma página 
    e determinar se há um EDITAL ATIVO DE APOIO 
    FINANCEIRO OU PROJETO COM INSCRIÇÕES ABERTAS.

    REGRAS OBRIGATÓRIAS PARA EXTRAÇÃO:
    1. Resumo: Exatamente duas frases sobre o foco.
    2. Prazo: Formato "DD de Mês de AAAA" ou "Inscrições Contínuas".
    3. Valor e Período: Se não estiver claro no texto, 
       retorne "Não especificado".
    4. Link: Use exatamente o valor "{url}".

    DIRETRIZES DE SEGURANÇA (ANTI-ALUCINAÇÃO RÍGIDA):
    - Se o texto recebido estiver vazio, contiver erros de rede 
      (como 403, 503, Cloudflare, Access Denied) ou se a página 
      for apenas notícias gerais sem nenhum edital aberto, 
      você DEVE retornar 'is_valid_edital': false.
    - É terminantemente proibido inventar dados, datas 
      ou supor regras que não estejam escritas no texto.

    TEXTO DA PÁGINA:
    {texto}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json', 'response_schema': EditalOutput}
        )
        res_dict = json.loads(response.text)
        res_dict["Link"] = url
        return res_dict
    except Exception as e:
        print(f"[{url}] Erro Gemini: {e}")
        return None

def run_scraper():
    print("Iniciando varredura...\n")
    root = os.path.dirname(os.path.abspath(__file__))
    path_json = os.path.join(root, 'editais.json')
    path_urls = os.path.join(root, 'urls.txt')
    
    if not os.path.exists(path_urls):
        print(f"Erro: {path_urls} ausente.")
        return

    urls = []
    with open(path_urls, 'r', encoding='utf-8') as f:
        for l in f:
            l_clean = l.strip()
            if l_clean and not l_clean.startswith('#'):
                urls.append(l_clean)

    if not urls:
        print("Nenhuma URL encontrada.")
        return

    ex_editais = []
    if os.path.exists(path_json):
        with open(path_json, 'r', encoding='utf-8') as f:
            try:
                ex_editais = json.load(f)
            except:
                print("Erro ao ler JSON. Resetando.")

    ex_links = {e.get("Link") for e in ex_editais}
    novos = []
    details = []
    stats = {"total_sites": len(urls), "sucessos": 0, "recusados": 0, "erros": 0}

    for u in urls:
        txt, err = obter_texto_pagina(u)
        if err:
            print(f"[{u}] Erro: {err}")
            stats["erros"] += 1
            details.append({"url": u, "status": "Erro", "info": err})
            continue
        if u in ex_links:
            print(f"[{u}] Já existe.")
            stats["sucessos"] += 1
            details.append({"url": u, "status": "Sucesso", "info": "Já monitorado"})
            continue
        
        data = analisar_edital_com_gemini(txt, u)
        if data:
            if data.get("is_valid_edital"):
                print(f"[{u}] ✅ Sucesso!")
                stats["sucessos"] += 1
                novos.append({k: v for k, v in data.items() if k != "is_valid_edital"})
                details.append({"url": u, "status": "Sucesso", "info": data.get("Nomes")})
            else:
                print(f"[{u}] ❌ Edital não identificado!")
                stats["recusados"] += 1
                details.append({"url": u, "status": "Edital não identificado", "info": "Nenhum edital ativo"})
        else:
            stats["erros"] += 1
            details.append({"url": u, "status": "Erro", "info": "Falha análise"})

    if novos:
        with open(path_json, 'w', encoding='utf-8') as f:
            json.dump(novos + ex_editais, f, ensure_ascii=False, indent=4)

    status_data = {
        "ultima_atualizacao": datetime.now().strftime('%d/%m/%Y às %H:%M'),
        "resumo": stats,
        "detalhes": details
    }
    with open(os.path.join(root, 'status.json'), 'w', encoding='utf-8') as f:
        json.dump(status_data, f, ensure_ascii=False, indent=4)
    print("\nConcluído!")

if __name__ == "__main__":
    run_scraper()
