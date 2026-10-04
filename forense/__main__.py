"""Linha de comando: python -m forense <comando> ...

  diagnostico                 verifica a instalação
  processar <pasta_do_caso>   extrai, indexa e faz a triagem (retomável)
  verificar <pasta_do_caso>   confere a integridade (hashes) contra o manifesto
  relatorio <pasta_do_caso>   gera o relatório Word de apoio
  exportar-sgnt <pasta>       exporta o corpus (texto e caixas do OCR) para a skill sg-nt:instrucao
  ia [--modelo M] [--sem-medir]   confere a IA local (Ollama) e mede a velocidade
"""

import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="python -m forense", description="doc-forense")
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("diagnostico")
    pia = sub.add_parser("ia")
    pia.add_argument("--modelo", default=None)
    pia.add_argument("--sem-medir", action="store_true")
    p = sub.add_parser("processar")
    p.add_argument("caso", type=Path)
    p.add_argument("--workers", type=int, default=None, help="processos paralelos (padrão: metade dos núcleos lógicos)")
    p.add_argument("--forcar-ocr", action="store_true", help="faz OCR mesmo em páginas com texto digital")
    p.add_argument("--dpi", type=int, default=None)
    for nome in ("verificar", "relatorio", "exportar-sgnt"):
        sub.add_parser(nome).add_argument("caso", type=Path)
    args = ap.parse_args(argv)

    if args.comando == "diagnostico":
        from .diagnostico import imprimir
        return 0 if imprimir() else 1

    if args.comando == "ia":
        from .ia import MODELO_PADRAO, imprimir as imprimir_ia
        return 0 if imprimir_ia(args.modelo or MODELO_PADRAO, medir=not args.sem_medir) else 1

    from .caso import Caso
    caso = Caso(args.caso)
    if not caso.existe():
        print(f"Pasta de caso inválida (sem subpasta 'originais'): {caso.raiz}")
        return 2

    if args.comando == "processar":
        from .processamento import processar_caso
        parametros = {}
        if args.forcar_ocr:
            parametros["forcar_ocr"] = True
        if args.dpi:
            parametros["dpi"] = args.dpi
        resumo = processar_caso(caso, parametros, workers=args.workers, log=lambda m: print(m, flush=True))
        return 0 if resumo["erros"] == 0 else 1

    if args.comando == "verificar":
        r = caso.verificar_integridade()
        print("Integridade OK" if r["ok"] else "PROBLEMAS ENCONTRADOS:")
        for prob in r["problemas"]:
            print("  -", prob)
        print(f"Originais conferidos: {r['conferidos']}")
        return 0 if r["ok"] else 1

    if args.comando == "exportar-sgnt":
        from .exportar_sgnt import exportar
        r = exportar(caso)
        print(f"{r['documentos']} documentos, {r['arquivos_txt']} arquivos de texto, "
              f"{r['paginas_com_caixas']} páginas com caixas de OCR, {r['paginas_duvidosas']} duvidosas")
        print(r["pasta"])
        return 0

    if args.comando == "relatorio":
        from .relatorio import gerar_relatorio
        print(gerar_relatorio(caso))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
