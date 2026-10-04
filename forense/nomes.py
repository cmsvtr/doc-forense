"""Reconhecimento de empresas, pessoas, e-mails e contratos sem IA, para a triagem.

São regras: rápidas, explicáveis e com erros previsíveis. Empresa: CNPJ ou nome com sufixo
societário. Pessoa: CPF, nome em cabeçalho de e-mail, ou prenome comum seguido de sobrenome.
O objetivo é priorizar a leitura, não montar o dramatis personae (isso é da etapa 2, validado).
"""

import re
import unicodedata

from .extrator_html import extrair_cabecalhos_email
from .regex_br import extrair_cnpjs, extrair_cpfs

# Prenomes mais comuns no Brasil (amostra ampla; nomes compostos entram pelo primeiro).
PRENOMES = set("""
adriana adriano afonso alberto alessandra alessandro alex alexandre alice aline alvaro amanda ana anderson andre
andrea andreia angela antonia antonio aparecida arthur augusto barbara beatriz benedito bernardo bianca bruna bruno
caio camila carla carlos carmen carolina caroline cassio catarina cecilia celia celso cesar charles cicero clara
claudia claudio cleber cristiane cristiano cristina daniel daniela danilo davi david debora denise diego diogo
douglas edson eduarda eduardo elaine eliana eliane elias elisa elizabete emerson enzo erica erika estela eugenio
evandro fabiana fabiano fabio fabricio felipe fernanda fernando flavia flavio francisca francisco gabriel gabriela
geraldo gilberto gilmar giovana giovanni glaucia gloria graziela guilherme gustavo helena helio heloisa henrique
hugo igor isabel isabela isadora ivan ivone jaqueline jefferson jessica joana joao joaquim jonas jorge jose josefa
josiane julia juliana juliano julio karina katia laura leandro leila leonardo leticia lidia lilian livia lorena
lourdes lucas lucia luciana luciano luis luiz luiza luzia manoel manuel marcela marcelo marcia marcio marco marcos
margarete maria mariana marilene marina mario marlene marta mateus matheus mauricio mauro michele miguel milena
milton miriam monica murilo nadia natalia nathalia nelson nicolas nilton oscar osvaldo otavio pamela patricia paula
paulo pedro priscila rafael rafaela raimunda raimundo raquel regina reinaldo renan renata renato ricardo roberta
roberto robson rodrigo rogerio romulo ronaldo rosa rosana rosangela rubens samuel sandra sara sebastiao sergio silvia
silvio simone sofia solange sonia stefani suelen tais tania tatiana teresa thais thiago tiago valeria valter vanessa
vera veronica victor vinicius virginia vitor vitoria viviane wagner waldir walter wanderley washington wellington
wesley willian wilson yara yasmin
""".split())
# Palavras que antecedem prenome em nomes de lugar ou instituição («Rua Paulo Afonso», «São Paulo»).
_NAO_PESSOA_ANTES = {"rua", "av", "avenida", "praca", "rodovia", "estrada", "travessa", "alameda", "escola",
                     "colegio", "hospital", "edificio", "condominio", "sao", "santa", "santo", "dom", "fundacao",
                     "instituto", "universidade", "ponte", "parque", "bairro", "vila", "jardim"}
_CONECTORES = {"da", "de", "do", "dos", "das", "e", "d"}

_SUFIXO_EMPRESA = r"(?:S\.?\s?/?\s?A\.?|LTDA\.?|Ltda\.?|EIRELI|Eireli|EPP|ME)"
_PALAVRA_MAIUSC = r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][\wÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç&'.\-]*"
EMPRESA_RE = re.compile(
    rf"\b((?:{_PALAVRA_MAIUSC}\s+(?:(?:de|da|do|dos|das|e)\s+)?){{1,6}}){_SUFIXO_EMPRESA}(?![\w])"
    rf"|\b(Cons[óo]rcio\s+(?:{_PALAVRA_MAIUSC}\s?){{1,5}})")
_INICIO_FALSO = {"de", "para", "ao", "aos", "a", "o", "e", "em", "da", "do", "pela", "pelo", "cc", "assunto", "cnpj"}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def chave(nome: str) -> str:
    base = _sem_acento(nome.lower())
    base = re.sub(r"\bs\s*[./]?\s*a\b\.?", " sa ", base)
    return " ".join(re.findall(r"[a-z0-9]+", base))


def empresas(texto: str) -> set[str]:
    """Chaves das empresas citadas: CNPJs e nomes com sufixo societário ou «Consórcio»."""
    achadas = {"cnpj:" + re.sub(r"\D", "", c) for c in extrair_cnpjs(texto)}
    for m in EMPRESA_RE.finditer(texto):
        nome = (m.group(0) or "").strip(" .,;")
        palavras = nome.split()
        while palavras and _sem_acento(palavras[0].lower()).strip(".:") in _INICIO_FALSO:
            palavras = palavras[1:]
        if len(palavras) >= 2:
            achadas.add(chave(" ".join(palavras)))
    return achadas


def contar_empresas(chaves: set[str]) -> int:
    """Empresas distintas. A mesma empresa costuma aparecer pelo nome e pelo CNPJ: conta-se o maior
    dos dois números, e não a soma, para não dobrar a contagem."""
    cnpjs = sum(1 for c in chaves if c.startswith("cnpj:"))
    return max(cnpjs, len(chaves) - cnpjs)


def pessoas(texto: str, emails: list[dict] | None = None) -> set[str]:
    """Chaves das pessoas citadas: CPFs, nomes nos cabeçalhos de e-mail e prenome + sobrenome."""
    achadas = {"cpf:" + re.sub(r"\D", "", c) for c in extrair_cpfs(texto)}
    for msg in emails or []:
        for campo in ("de", "para", "cc"):
            for parte in re.split(r"[;,]", msg.get(campo) or ""):
                nome = re.sub(r"<[^>]*>|\S+@\S+|[\"']", " ", parte).strip()
                if len(nome.split()) >= 2:
                    achadas.add(chave(nome))
    tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[^\W\d_]+", texto)]

    def junto(a, b):  # duas palavras vizinhas só com espaço entre elas (sem quebra de linha nem pontuação)
        return re.fullmatch(r"[ \t]+", texto[tokens[a][2]:tokens[b][1]]) is not None

    i = 0
    while i < len(tokens):
        w = tokens[i][0]
        if (not w[0].isupper() or _sem_acento(w.lower()) not in PRENOMES
                or (i > 0 and _sem_acento(tokens[i - 1][0].lower()) in _NAO_PESSOA_ANTES)):
            i += 1
            continue
        nome, j = [w], i + 1
        while j < len(tokens) and len(nome) < 6 and junto(j - 1, j):
            prox = tokens[j][0]
            if (prox.lower() in _CONECTORES and j + 1 < len(tokens) and junto(j, j + 1)
                    and tokens[j + 1][0][0].isupper()):
                nome += [prox.lower(), tokens[j + 1][0]]
                j += 2
            elif prox[0].isupper() and len(prox) > 1:
                nome.append(prox)
                j += 1
            else:
                break
        if any(x not in _CONECTORES for x in nome[1:]):
            achadas.add(chave(" ".join(nome)))
        i = j  # «Ana Paula de Souza» não gera também «Paula de Souza»
    return achadas


def emails_do_documento(doc: dict) -> list[dict]:
    """Cabeçalhos de e-mail: os do HTML e, num PDF (e-mail impresso), os das 3 primeiras páginas."""
    if doc.get("emails"):
        return doc["emails"]
    if doc["arquivo"]["tipo"] != "pdf":
        return []
    texto = "\n".join(pg.get("texto") or "" for pg in doc["paginas"][:3])
    return extrair_cabecalhos_email(texto)


_TITULO_CONTRATO = re.compile(
    r"\b(contrato|termo aditivo|aditivo contratual|instrumento particular|termo de compromisso|acordo de "
    r"(?:cooperação|parceria|consórcio|acionistas|cotistas)|compromisso de constituição de consórcio)\b", re.I)
_SINAIS_CONTRATO = re.compile(r"\b(contratante|contratada|cl[áa]usula|partes contratantes|objeto do contrato|vig[êe]ncia)\b", re.I)


def e_contrato(doc: dict) -> bool:
    """Título de contrato no início e sinais de contrato (partes, cláusulas) no texto."""
    sei = doc.get("sei") or {}
    if re.search(r"contrato|aditivo", sei.get("tipo_no_nome") or "", re.I) and sei.get("tipo_no_nome_confiavel"):
        return True
    inicio = "\n".join(pg.get("texto") or "" for pg in doc["paginas"][:2])[:3000]
    texto = "\n".join(pg.get("texto") or "" for pg in doc["paginas"][:10])
    return bool(_TITULO_CONTRATO.search(inicio[:600])) and len(_SINAIS_CONTRATO.findall(texto)) >= 3


_COMUNICACAO = [  # (tipo, padrão no início do documento, sem acento e em minúsculas), na ordem de preferência
    ("transcrição de conversa", re.compile(r"\btranscri(cao|coes)\b|\binterlocutor(es)?\b|\b(ligacao|dialogo|conversa) telefonic")),
    ("ata de reunião", re.compile(r"\bata\b.{0,60}\breuniao\b|\bata da\b.{0,40}\b(reuniao|assembleia)\b|\b(presentes|participantes)\s*:")),
    ("memorando", re.compile(r"\bmemorando\b|\bcomunicacao interna\b|\bmemo\s*n")),
    ("carta ou ofício", re.compile(r"\b(prezad[oa]s?|ilustrissim[oa]|caro senhor|cara senhora)\b")),
    ("fax", re.compile(r"\bfax\b.{0,40}\b(de|para|n[o.]?|pagina)")),
]
_FECHO_CARTA = re.compile(r"\b(atenciosamente|cordialmente|respeitosamente|saudacoes)\b")


def tipo_comunicacao(doc: dict) -> str | None:
    """Tipo de comunicação entre pessoas, ou None. Ofício da própria autoridade (ato do SEI) não conta: é
    expediente do processo, não prova."""
    from .comunicacoes import mensagens_de_chat

    if emails_do_documento(doc):
        return "e-mail"
    if len(mensagens_de_chat(doc)) >= 2:
        return "conversa"
    sei = doc.get("sei") or {}
    inicio = _sem_acento("\n".join(pg.get("texto") or "" for pg in doc["paginas"][:2])[:4000].lower())
    for tipo, padrao in _COMUNICACAO:
        if not padrao.search(inicio):
            continue
        if tipo == "carta ou ofício":
            if sei.get("especie_ato") or not _FECHO_CARTA.search(_sem_acento(
                    "\n".join(pg.get("texto") or "" for pg in doc["paginas"][:6]).lower())):
                continue
        return tipo
    return None
