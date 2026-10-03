"""Estrutura de um caso em disco, manifesto de custódia, log de auditoria e verificação de integridade.

casos/<nome>/
    originais/        documentos de entrada (nunca alterados pelo aplicativo)
    extraido/         camada bruta: um JSON por documento (texto fiel, página a página)
    analise/          camada analítica: triagem (e, na etapa 2, achados da IA)
    relatorios/       relatórios Word gerados
    indice.sqlite     índice de busca, descartável e reconstruído a partir de extraido/
    manifesto.json    cadeia de custódia (hashes de originais e extrações)
    auditoria.jsonl   registro de eventos
"""

import getpass
import json
import os
import platform
import re
import tempfile
from datetime import datetime
from pathlib import Path

from . import EXTRATOR_VERSAO, __version__
from .ocr import sha256_arquivo

EXTENSOES = {".pdf": "pdf", ".html": "html", ".htm": "html"}


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def escrever_json_atomico(destino: Path, dados) -> None:
    """Grava em arquivo temporário e troca de uma vez: interrupção nunca deixa JSON pela metade."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, destino)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def ler_json(caminho: Path):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def nome_seguro(nome: str) -> str:
    nome = re.sub(r"[^\w\-. ]", "_", nome.strip(), flags=re.UNICODE).strip(" .")
    return nome or "caso"


class Caso:
    def __init__(self, raiz: Path):
        self.raiz = Path(raiz).resolve()
        self.originais = self.raiz / "originais"
        self.extraido = self.raiz / "extraido"
        self.analise = self.raiz / "analise"
        self.relatorios = self.raiz / "relatorios"
        self.indice = self.raiz / "indice.sqlite"
        self.manifesto = self.raiz / "manifesto.json"
        self.auditoria = self.raiz / "auditoria.jsonl"
        self.progresso = self.raiz / "progresso.json"
        self.log_execucao = self.raiz / "execucao.log"

    @property
    def nome(self) -> str:
        return self.raiz.name

    @classmethod
    def criar(cls, base: Path, nome: str) -> "Caso":
        caso = cls(Path(base) / nome_seguro(nome))
        for p in (caso.originais, caso.extraido, caso.analise, caso.relatorios):
            p.mkdir(parents=True, exist_ok=True)
        if not caso.auditoria.exists():
            caso.registrar("caso_criado")
        return caso

    def existe(self) -> bool:
        return self.originais.is_dir()

    # ------------------------------------------------------------ originais

    def listar_originais(self) -> tuple[list[Path], list[Path]]:
        """(suportados, ignorados), em ordem estável. Inclui subpastas."""
        suportados, ignorados = [], []
        if not self.originais.is_dir():
            return suportados, ignorados
        for p in sorted(self.originais.rglob("*")):
            if not p.is_file() or p.name.startswith(("~$", ".")):
                continue
            (suportados if p.suffix.lower() in EXTENSOES else ignorados).append(p)
        return suportados, ignorados

    def relativo(self, p: Path) -> str:
        return p.resolve().relative_to(self.raiz).as_posix()

    # ------------------------------------------------------------ extrações

    def caminho_json(self, sha256: str) -> Path:
        return self.extraido / f"{sha256[:16]}.json"

    def documentos(self) -> list[dict]:
        """Todos os JSON da camada bruta, ordenados pelo nome do primeiro arquivo."""
        docs = []
        if self.extraido.is_dir():
            for p in self.extraido.glob("*.json"):
                try:
                    docs.append(ler_json(p))
                except (OSError, json.JSONDecodeError):
                    continue
        docs.sort(key=lambda d: d["arquivo"]["nome"].lower())
        return docs

    # ------------------------------------------------------------ auditoria

    def registrar(self, evento: str, **dados) -> None:
        linha = {"quando": agora(), "usuario": _usuario(), "evento": evento, **dados}
        with open(self.auditoria, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")

    def eventos(self) -> list[dict]:
        if not self.auditoria.exists():
            return []
        with open(self.auditoria, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    # ------------------------------------------------------------ manifesto

    def gerar_manifesto(self, ferramentas: dict, parametros: dict) -> dict:
        _, ignorados = self.listar_originais()
        documentos = []
        for d in self.documentos():
            caminho = self.caminho_json(d["arquivo"]["sha256"])
            documentos.append({
                "sha256_original": d["arquivo"]["sha256"],
                "arquivos": d["arquivo"]["caminhos"],
                "tamanho_bytes": d["arquivo"]["tamanho_bytes"],
                "extracao_json": self.relativo(caminho),
                "extracao_sha256": sha256_arquivo(caminho),
                "status": d["status"],
                "paginas": len(d["paginas"]),
                "paginas_ocr": sum(1 for p in d["paginas"] if p["metodo"] == "ocr"),
                "extraido_em": d["extracao"]["extraido_em"],
            })
        manifesto = {
            "schema": "doc-forense/manifesto@1",
            "caso": self.nome,
            "gerado_em": agora(),
            "gerado_por": _usuario(),
            "aplicativo": {"nome": "doc-forense", "versao": __version__, "extrator": EXTRATOR_VERSAO},
            "sistema": {"so": platform.platform(), "python": platform.python_version()},
            "ferramentas": ferramentas,
            "parametros": parametros,
            "total_documentos": len(documentos),
            "documentos": documentos,
            "arquivos_ignorados": [self.relativo(p) for p in ignorados],
        }
        escrever_json_atomico(self.manifesto, manifesto)
        hash_manifesto = sha256_arquivo(self.manifesto)
        (self.raiz / "manifesto.json.sha256").write_text(f"{hash_manifesto}  manifesto.json\n", encoding="utf-8")
        self.registrar("manifesto_gerado", sha256=hash_manifesto, documentos=len(documentos))
        return manifesto

    def verificar_integridade(self) -> dict:
        """Recalcula hashes e compara com o manifesto. Não altera nada."""
        resultado = {"verificado_em": agora(), "ok": True, "problemas": [], "conferidos": 0}
        if not self.manifesto.exists():
            resultado.update(ok=False, problemas=["Manifesto ainda não existe: processe os documentos."])
            return resultado

        problemas = resultado["problemas"]
        arquivo_hash = self.raiz / "manifesto.json.sha256"
        if arquivo_hash.exists():
            esperado = arquivo_hash.read_text(encoding="utf-8").split()[0]
            if sha256_arquivo(self.manifesto) != esperado:
                problemas.append("O próprio manifesto.json foi alterado depois de gerado.")

        manifesto = ler_json(self.manifesto)
        conhecidos = set()
        for doc in manifesto["documentos"]:
            for rel in doc["arquivos"]:
                conhecidos.add(rel)
                p = self.raiz / rel
                if not p.exists():
                    problemas.append(f"Original ausente: {rel}")
                elif sha256_arquivo(p) != doc["sha256_original"]:
                    problemas.append(f"Original ALTERADO (hash diferente): {rel}")
                else:
                    resultado["conferidos"] += 1
            pj = self.raiz / doc["extracao_json"]
            if not pj.exists():
                problemas.append(f"Extração ausente: {doc['extracao_json']}")
            elif sha256_arquivo(pj) != doc["extracao_sha256"]:
                problemas.append(f"Extração ALTERADA (hash diferente): {doc['extracao_json']}")

        suportados, _ = self.listar_originais()
        for p in suportados:
            if self.relativo(p) not in conhecidos:
                problemas.append(f"Original novo, ainda não processado: {self.relativo(p)}")

        resultado["ok"] = not problemas
        self.registrar("integridade_verificada", ok=resultado["ok"], problemas=len(problemas))
        return resultado


def _usuario() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "desconhecido"
