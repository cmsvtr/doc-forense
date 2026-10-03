"""Extração determinística de identificadores brasileiros, datas, valores e e-mails.

Tudo aqui é regex com validação. Nada depende de IA.
"""

import re
from datetime import date

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}
_MESES_RE = "|".join(sorted(MESES, key=len, reverse=True))

ANO_MIN, ANO_MAX = 1980, 2035

# ---------------------------------------------------------------- CPF / CNPJ

CPF_RE = re.compile(r"(?<![\d.])(\d{3}\.\d{3}\.\d{3}-\d{2})(?![\d])")
# CNPJ formatado: numérico ou alfanumérico (IN RFB 2.229/2024, vigente desde jul/2026).
CNPJ_FMT_RE = re.compile(r"(?<![0-9A-Z.])([0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2})(?!\d)")
# CNPJ sem pontuação: só numérico (14 dígitos isolados), validado pelo DV.
CNPJ_NUM_RE = re.compile(r"(?<!\d)(\d{14})(?!\d)")


def cpf_valido(cpf: str) -> bool:
    d = re.sub(r"\D", "", cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        dv = (soma * 10) % 11 % 10
        if dv != int(d[n]):
            return False
    return True


def _valor_cnpj(c: str) -> int:
    # Regra do CNPJ alfanumérico: valor = código ASCII - 48 (0-9 -> 0-9, A -> 17 ...).
    return ord(c) - 48


def cnpj_valido(cnpj: str) -> bool:
    s = re.sub(r"[./-]", "", cnpj.upper())
    if len(s) != 14 or not re.fullmatch(r"[0-9A-Z]{12}\d{2}", s):
        return False
    if s == s[0] * 14:
        return False
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(_valor_cnpj(s[i]) * pesos[i] for i in range(tamanho))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(s[tamanho]):
            return False
    return True


def formatar_cnpj(s: str) -> str:
    s = re.sub(r"[./-]", "", s.upper())
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


def extrair_cpfs(texto: str) -> list[str]:
    return [m.group(1) for m in CPF_RE.finditer(texto) if cpf_valido(m.group(1))]


def extrair_cnpjs(texto: str) -> list[str]:
    achados = [m.group(1) for m in CNPJ_FMT_RE.finditer(texto) if cnpj_valido(m.group(1))]
    achados += [formatar_cnpj(m.group(1)) for m in CNPJ_NUM_RE.finditer(texto) if cnpj_valido(m.group(1))]
    return achados


# ---------------------------------------------------------------- Datas

DATA_NUM_RE = re.compile(r"(?<![\d/.\-])(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?![\d]|[/.\-]\d)")
DATA_EXT_RE = re.compile(
    rf"\b(\d{{1,2}})(?:º|°|o)?\s+de\s+({_MESES_RE})\s+de\s+(\d{{4}})\b", re.IGNORECASE
)
MES_ANO_RE = re.compile(rf"\b({_MESES_RE})\s+(?:de\s+)?(\d{{4}})\b", re.IGNORECASE)


def _data_ok(a: int, m: int, d: int) -> bool:
    if not (ANO_MIN <= a <= ANO_MAX):
        return False
    try:
        date(a, m, d)
        return True
    except ValueError:
        return False


def extrair_datas(texto: str) -> list[dict]:
    """Datas encontradas, com posição. precisao = 'dia' ou 'mes'."""
    achados: list[dict] = []
    ocupado: list[tuple[int, int]] = []

    def livre(i: int, f: int) -> bool:
        return all(f <= a or i >= b for a, b in ocupado)

    for m in DATA_EXT_RE.finditer(texto):
        d, mes, a = int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3))
        if _data_ok(a, mes, d):
            achados.append({"data": f"{a:04d}-{mes:02d}-{d:02d}", "precisao": "dia",
                            "bruto": m.group(0), "inicio": m.start(), "fim": m.end()})
            ocupado.append((m.start(), m.end()))

    for m in DATA_NUM_RE.finditer(texto):
        d, sep, mes, a_txt = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        if len(a_txt) == 2:
            if sep != "/":
                continue  # "1.2.24" costuma ser versão, não data
            a = 2000 + int(a_txt) if int(a_txt) <= 69 else 1900 + int(a_txt)
        else:
            a = int(a_txt)
        if _data_ok(a, mes, d) and livre(m.start(), m.end()):
            achados.append({"data": f"{a:04d}-{mes:02d}-{d:02d}", "precisao": "dia",
                            "bruto": m.group(0), "inicio": m.start(), "fim": m.end()})
            ocupado.append((m.start(), m.end()))

    for m in MES_ANO_RE.finditer(texto):
        mes, a = MESES[m.group(1).lower()], int(m.group(2))
        if ANO_MIN <= a <= ANO_MAX and livre(m.start(), m.end()):
            achados.append({"data": f"{a:04d}-{mes:02d}", "precisao": "mes",
                            "bruto": m.group(0), "inicio": m.start(), "fim": m.end()})
            ocupado.append((m.start(), m.end()))

    achados.sort(key=lambda x: x["inicio"])
    return achados


# ---------------------------------------------------------------- Valores e e-mails

VALOR_RE = re.compile(
    r"R\$\s?(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?"
    r"(?:\s*(mil|milh[aã]o|milh[oõ]es|bilh[aã]o|bilh[oõ]es|mi|bi)\b)?",
    re.IGNORECASE,
)
_MULT = {"mil": 1e3, "mi": 1e6, "milhao": 1e6, "milhão": 1e6, "milhoes": 1e6, "milhões": 1e6,
         "bi": 1e9, "bilhao": 1e9, "bilhão": 1e9, "bilhoes": 1e9, "bilhões": 1e9}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def extrair_valores(texto: str) -> list[dict]:
    saida = []
    for m in VALOR_RE.finditer(texto):
        inteiro = float(m.group(1).replace(".", ""))
        centavos = float("0." + m.group(2)) if m.group(2) else 0.0
        mult = _MULT.get((m.group(3) or "").lower(), 1.0)
        saida.append({"bruto": m.group(0).strip(), "valor": round((inteiro + centavos) * mult, 2)})
    return saida


def extrair_emails(texto: str) -> list[str]:
    return [e.lower() for e in EMAIL_RE.findall(texto)]


# ---------------------------------------------------------------- Agregação por documento

def entidades_por_pagina(paginas: list[dict]) -> dict:
    """Agrupa entidades do documento indicando em quais páginas aparecem."""
    acumulado: dict[str, dict[str, set]] = {"cnpjs": {}, "cpfs": {}, "emails": {}, "valores": {}}
    datas: dict[tuple, dict] = {}
    for p in paginas:
        texto, n = p.get("texto") or "", p["n"]
        for v in extrair_cnpjs(texto):
            acumulado["cnpjs"].setdefault(v, set()).add(n)
        for v in extrair_cpfs(texto):
            acumulado["cpfs"].setdefault(v, set()).add(n)
        for v in extrair_emails(texto):
            acumulado["emails"].setdefault(v, set()).add(n)
        for v in extrair_valores(texto):
            acumulado["valores"].setdefault(v["bruto"], set()).add(n)
        for d in extrair_datas(texto):
            chave = (d["data"], d["precisao"])
            datas.setdefault(chave, {"data": d["data"], "precisao": d["precisao"], "paginas": set()})
            datas[chave]["paginas"].add(n)

    def lista(dic):
        return [{"valor": k, "paginas": sorted(v)} for k, v in sorted(dic.items())]

    return {
        "cnpjs": lista(acumulado["cnpjs"]),
        "cpfs": lista(acumulado["cpfs"]),
        "emails": lista(acumulado["emails"]),
        "valores": lista(acumulado["valores"]),
        "datas": [{**v, "paginas": sorted(v["paginas"])} for _, v in sorted(datas.items())],
    }
