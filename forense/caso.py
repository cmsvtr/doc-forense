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
import time
from datetime import datetime
from pathlib import Path

from . import EXTRATOR_VERSAO, __version__
from .ocr import sha256_arquivo

EXTENSOES = {".pdf": "pdf", ".html": "html", ".htm": "html", ".txt": "txt"}


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def substituir(origem, destino, tentativas: int = 40) -> None:
    """os.replace que resiste ao Windows.

    No Windows, a troca é recusada («Acesso negado», WinError 5 ou 32) enquanto outro processo
    estiver com o destino aberto: a interface lendo o progresso, o antivírus examinando o arquivo
    novo, o OneDrive sincronizando. A trava dura milissegundos; tenta de novo por até ~10 s.
    """
    espera = 0.02
    for i in range(tentativas):
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if i == tentativas - 1:
                raise
            time.sleep(espera)
            espera = min(espera * 2, 0.5)


def escrever_json_atomico(destino: Path, dados) -> None:
    """Grava em arquivo temporário e troca de uma vez: interrupção nunca deixa JSON pela metade."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        substituir(tmp, destino)
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

    def destino_de_envio(self, nome_enviado: str) -> Path:
        """Onde gravar um arquivo enviado pelo navegador, mantendo as subpastas.

        No envio de pasta, o navegador manda o caminho relativo («SEI_…/[104]-1157123_Anexo/Doc. 1.PDF»):
        é a pasta que dá o número SEI aos anexos, então o caminho é preservado. Partes vazias, «.»
        e «..» são descartadas, para nada ser gravado fora da pasta de originais.
        """
        partes = [p for p in re.split(r"[\\/]+", nome_enviado) if p not in ("", ".", "..")]
        partes = [re.sub(r'[<>:"|?*\x00-\x1f]', "_", p).rstrip(" .") or "_" for p in partes]
        if not partes:
            raise ValueError(f"Nome de arquivo inválido: {nome_enviado!r}")
        destino = self.originais.joinpath(*partes).resolve()
        if not destino.is_relative_to(self.originais.resolve()):
            raise ValueError(f"Caminho fora da pasta de originais: {nome_enviado!r}")
        return destino

    def sem_pasta_de_origem(self) -> list[Path]:
        """Arquivos «Doc. N» sem número SEI no caminho: a pasta de anexo, que dá o número, se perdeu
        (típico de arquivo enviado solto pelo navegador)."""
        from .sei import identificar

        suportados, _ = self.listar_originais()
        saida = []
        for p in suportados:
            rel = p.resolve().relative_to(self.originais.resolve()).as_posix()
            if re.match(r"^\s*doc(umento)?\.?\s*n?[º°o.]?\s*\d", p.stem, re.IGNORECASE) and not identificar(rel, p.suffix.lower(), ""):
                saida.append(p)
        return saida

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


def excluir_caso(base: Path, caso: "Caso") -> dict:
    """Manda a pasta do caso para a Lixeira (recuperável) e deixa, fora dela, o registro da exclusão:
    nome, data, usuário e o hash do manifesto, para a cadeia de custódia mostrar que o caso existiu.
    Se a Lixeira não estiver disponível (pasta de rede, por exemplo), recusa em vez de apagar de vez."""
    from send2trash import send2trash

    from .processamento import em_execucao

    if not caso.existe():
        raise FileNotFoundError(f"Caso não encontrado: {caso.raiz}")
    if em_execucao(caso):
        raise RuntimeError("Há um processamento em andamento neste caso. Espere terminar para excluir.")
    if caso.raiz.resolve().parent != Path(base).resolve():
        raise PermissionError("Só se excluem pastas de caso de dentro da pasta de casos.")
    hash_manifesto = None
    arq = caso.raiz / "manifesto.json.sha256"
    if arq.exists():
        hash_manifesto = arq.read_text(encoding="utf-8").split()[0]
    suportados, _ = caso.listar_originais()
    registro = {"quando": agora(), "usuario": _usuario(), "evento": "caso_excluido", "caso": caso.nome,
                "destino": "Lixeira", "originais": len(suportados), "manifesto_sha256": hash_manifesto}
    try:
        send2trash(str(caso.raiz))
    except Exception as e:
        raise RuntimeError(f"Não foi possível mandar o caso para a Lixeira ({e}). Nada foi apagado.") from e
    with open(Path(base) / "_excluidos.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
