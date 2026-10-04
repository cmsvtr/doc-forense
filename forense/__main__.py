"""Linha de comando: python -m forense <comando> ...

  diagnostico                 verifica a instalação
  processar <pasta_do_caso>   extrai, indexa e faz a triagem (retomável)
  verificar <pasta_do_caso>   confere a integridade (hashes) contra o manifesto
  relatorio <pasta_do_caso>   gera o relatório Word de apoio
  exportar-sgnt <pasta>       exporta o corpus (texto e caixas do OCR) para a skill sg-nt:instrucao
  ia [--modelo M] [--sem-medir]   confere a IA local (Ollama) e mede a velocidade
  analisar-ia <pasta> [--primeiros N] [--documentos id,id] [--modelo M]   etapa 2: extração com IA
  indexar-vetores <pasta>     prepara a busca por significado (vetores no Ollama)
  importar <pasta_do_caso> <pasta_de_origem>   copia uma pasta de autos para o caso, com as subpastas
"""

import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="python -m forense", description="Olho Vivo e Faro Fino")
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
    pa = sub.add_parser("analisar-ia")
    pa.add_argument("caso", type=Path)
    pa.add_argument("--primeiros", type=int, default=None, help="só os N primeiros da triagem")
    pa.add_argument("--documentos", default=None, help="ids separados por vírgula")
    pa.add_argument("--modelo", default=None)
    pa.add_argument("--palavras", type=int, default=None, help="palavras por trecho")
    pi = sub.add_parser("importar")
    pi.add_argument("caso", type=Path)
    pi.add_argument("origem", type=Path)
    for nome in ("verificar", "relatorio", "exportar-sgnt", "indexar-vetores"):
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

    if args.comando == "analisar-ia":
        from .analise_ia import PALAVRAS_POR_TRECHO, analisar_caso
        from .ia import MODELO_PADRAO
        r = analisar_caso(caso, args.modelo or MODELO_PADRAO,
                          documentos=args.documentos.split(",") if args.documentos else None,
                          primeiros=args.primeiros, palavras_max=args.palavras or PALAVRAS_POR_TRECHO,
                          log=lambda m: print(m, flush=True))
        return 0 if r["erros"] == 0 else 1

    if args.comando == "importar":
        from .importar import importar_pasta
        from .processamento import Progresso, em_execucao
        if em_execucao(caso):
            print("Já existe um processamento em andamento para este caso.")
            return 1
        with Progresso(caso) as prog:
            prog.atualizar(etapa=f"importando {args.origem.name}", total=0, concluidos=0)
            r = importar_pasta(caso, args.origem, log=lambda m: print(m, flush=True),
                               progresso=lambda k, n, nome: prog.atualizar(total=n, concluidos=k, atual=nome))
            prog.atualizar(etapa="concluído", resumo=r)
        return 0 if r["erros"] == 0 else 1

    if args.comando == "indexar-vetores":
        from .processamento import Progresso, em_execucao
        from .vetores import indexar
        if em_execucao(caso):
            print("Já existe um processamento em andamento para este caso.")
            return 1
        with Progresso(caso) as prog:
            prog.atualizar(etapa="preparando a busca por significado", total=len(caso.documentos()), concluidos=0)
            r = indexar(caso, log=lambda m: print(m, flush=True),
                        progresso=lambda k, n, nome: prog.atualizar(concluidos=k, atual=nome))
            prog.atualizar(etapa="concluído", resumo=r)
        print(f"[✓] {r}")
        return 0

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
