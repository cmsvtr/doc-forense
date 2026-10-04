# doc-forense

Aplicativo local para organizar documentos de investigação de cartéis: recebe PDFs e HTMLs, faz OCR em português, cataloga, indexa para busca, prioriza a leitura e gera um relatório Word de apoio ao analista. **Tudo roda no computador do usuário**: nenhum documento sai da máquina.

> **Etapa 1 (esta versão):** extração, OCR, catálogo, busca, triagem, cadeia de custódia e relatório, **sem IA**.
> **Etapa 2 (planejada):** IA local para dramatis personae, linha do tempo e síntese, com citação conferida e revisão humana.

## Instalação (Windows 10/11)

1. Baixe esta pasta (botão *Code → Download ZIP* no GitHub) e descompacte num local fixo, por exemplo `Documentos\doc-forense`.
2. Clique duas vezes em **`instalar.bat`**. Ele:
   - instala o `uv`, que cuida do Python (sem precisar de administrador);
   - instala o Tesseract OCR pelo winget (o Windows pede permissão de administrador uma vez);
   - baixa o português do OCR para a pasta `tessdata` do aplicativo;
   - instala as bibliotecas e confere tudo;
   - cria o atalho **doc-forense** na área de trabalho.
3. Se o diagnóstico final mostrar `FALHA` no Tesseract logo depois de instalá-lo, feche a janela e rode o `instalar.bat` de novo.

Para atualizar: feche o aplicativo e clique duas vezes em **`atualizar.bat`**. Ele baixa a versão nova e troca só o código; os casos, o Python instalado e o idioma do OCR ficam como estão.

Para usar: clique no atalho **doc-forense** (ou em `abrir.bat`). O navegador abre o aplicativo em `http://localhost:8501`. A janela preta precisa ficar aberta enquanto você usa.

Linux/macOS: instale o `tesseract` com o idioma `por` pelo gerenciador de pacotes e rode `uv sync --no-dev` e depois `uv run --no-dev streamlit run app.py`.

## IA local (preparação para a Etapa 2)

A Etapa 2 usa uma IA que roda **neste computador** (Ollama com o modelo Qwen 2.5 7B). Nada é enviado para fora.

**Automático:** feche o app, rode o `atualizar.bat` e depois clique duas vezes em **`instalar_ia.bat`**. Ele instala o Ollama na pasta do usuário (sem administrador), baixa o modelo (cerca de 4,7 GB) e mede a velocidade.

**Teste de velocidade:** clique duas vezes em **`testar_ia.bat`**.

**Manual, se o automático falhar:**
1. Baixe e instale o Ollama: https://ollama.com/download (botão *Download for Windows*). Não precisa entrar com conta.
2. Depois de instalado, ele fica ativo em segundo plano (ícone perto do relógio).
3. Abra o *Prompt de Comando* e rode `ollama pull qwen2.5:7b` (download de cerca de 4,7 GB; se cair, rode de novo e ele continua).
4. Na pasta do doc-forense, rode `uv run --no-dev python -m forense ia` para conferir e medir a velocidade.

**Sigilo:** use só modelos que rodam no computador. Modelos com `cloud` no nome rodam nos servidores da Ollama; o `python -m forense ia` avisa se houver algum. Não defina a variável `OLLAMA_HOST`: sem ela, o Ollama só aceita conexões deste computador.

## Uso

1. **Crie um caso** na barra lateral.
2. **Entrada:** copie as **pastas dos autos como estão**, com as subpastas, para a pasta `originais` do caso. O nome da pasta de anexo traz o número SEI dos arquivos de dentro: um «Doc. 1.PDF» enviado solto perde a referência. O envio pelo navegador também é de pasta inteira, preservando as subpastas.
3. **Processar:** roda em segundo plano, então pode fechar o navegador. Se for interrompido, basta processar de novo: o que já foi feito não é refeito.
4. **Triagem:** ranking de documentos para priorizar a leitura, com o motivo de cada ponto (termo, página e trecho).
5. **Busca e perguntas:**
   - **Por palavra:** texto completo em todos os documentos, sem distinção de acentos (`"frase exata"`, `prefix*`, `termo1 OU termo2`).
   - **Pergunta:** combina a busca por palavra com a busca por significado (acha passagens sem as palavras exatas). Prepare uma vez com "Preparar busca por significado". As passagens encontradas aparecem primeiro; a resposta da IA é opcional, usa só essas passagens e cada afirmação traz o trecho conferido no documento.
6. **Documento:** texto página a página, com o método (digital ou OCR) e a confiança do OCR.
Nos resultados da Busca, nos trechos da Triagem e na aba Documento, o botão **📄 Abrir p. N** abre o original no Edge (ou no Chrome) já na página citada; sem esses navegadores, abre no leitor de PDF padrão.
7. **IA e revisão** (com a IA local instalada):
   - **Analisar:** escolha os documentos (por padrão, os primeiros da triagem).
   - **Revisar achados:** cada pessoa, empresa ou evento vem com o trecho do documento, a página e o botão para abrir o original. A máquina já descartou o que não encontrou no texto. Valide ou rejeite.
   - **Dramatis personae** e **Linha do tempo:** montados só com o que você validou.
8. **Relatório e custódia:** relatório Word de apoio, verificação de integridade e exportação para a skill `sg-nt:instrucao`.

**Excluir um caso:** na barra lateral, "Excluir caso". A pasta inteira vai para a Lixeira do Windows (recuperável) e a exclusão fica registrada em `casos/_excluidos.jsonl`, com o hash do manifesto.

## Linha de comando

```
uv run python -m forense diagnostico
uv run python -m forense processar  "casos/Meu caso"   [--workers 6] [--forcar-ocr]
uv run python -m forense verificar  "casos/Meu caso"
uv run python -m forense relatorio  "casos/Meu caso"
uv run python -m forense exportar-sgnt "casos/Meu caso"
```

## Pasta de um caso

```
casos/<nome>/
  originais/          documentos de entrada (nunca alterados)
  extraido/           CAMADA BRUTA: um JSON por documento (texto fiel, página a página)
    caixas/<id>/      caixas de palavra do OCR (TSV do Tesseract), por página
  analise/            CAMADA ANALÍTICA: triagem (na etapa 2, os achados da IA)
  relatorios/         relatórios Word
  indice.sqlite       índice de busca (descartável; é reconstruído a partir de extraido/)
  manifesto.json      cadeia de custódia: SHA-256 dos originais e das extrações, ferramentas, parâmetros
  auditoria.jsonl     registro de eventos (quem, quando, o quê)
  exportacao_sgnt/    corpus no formato da skill sg-nt:instrucao (quando exportado)
```

As duas camadas são separadas de propósito. A **bruta** é determinística e auditável e pode ser entregue. A **analítica** pode ser refeita (outros critérios, outro modelo de IA) sem tocar nas provas.

## Decisões de método

- **OCR por página, nunca por arquivo.** A página vai ao OCR quando tem menos de 200 caracteres de texto digital, ou quando uma imagem cobre a maior parte dela. O segundo caso é o escaneado com carimbo digital do SEI por cima ("Documento assinado eletronicamente…"): tem texto digital, mas o conteúdo está na imagem. Pular o OCR deixaria a página invisível à busca.
- **Confiança do OCR registrada por página.** Páginas abaixo de 70% (ou com menos de 20 palavras) geram alerta de conferência visual.
- **CPF e CNPJ validados pelo dígito verificador**, incluindo o CNPJ alfanumérico (IN RFB 2.229/2024).
- **Documentos do SEI identificados pelo número** (nome do arquivo, pasta de anexo ou cabeçalho), citados como "SEI nº 1234567, p. 3". O tipo que aparece no nome de um PDF não é tomado como verdade: é o que quem protocolou escolheu.
- **A triagem só prioriza.** É uma soma transparente de termos com peso (`forense/termos_cartel.py`, editável) e de sinais estruturais. Não classifica conduta.

## Integração com a skill sg-nt:instrucao

O botão "Exportar corpus sg-nt" (ou `exportar-sgnt`) grava, em `exportacao_sgnt/corpus/`, o formato da Fase 3 da skill:
- `_caixas/<arquivo>/pNNNN.tsv/.txt`;
- `<SEI>.txt`;
- `_cobertura.tsv` e `_ocr_duvidoso.tsv`.

Copie `_caixas` para `instrucao/corpus/` e rode o `build_corpus.py` com `--sem-ocr`: a skill reaproveita o OCR feito aqui (horas de processamento) em vez de refazê-lo.

Use a **sg-nt 0.2.2 ou mais nova**. Até a 0.2.1, o `build_corpus.py` tratava como digital a página escaneada com o carimbo do SEI e ignorava o OCR dela: o corpus ficava só com o carimbo, com cobertura de 100%. A 0.2.2 aplica a mesma regra do doc-forense (imagem em metade da página ou mais e menos de 1.500 caracteres nativos vão ao OCR). Testado com o `build_corpus.py` da 0.2.2, inclusive com `--sem-ocr` sobre as caixas exportadas daqui.

## Limitações conhecidas

- Página escaneada girada (de lado ou de ponta-cabeça) sai com OCR ruim; a detecção de orientação ainda não foi implementada.
- Formatos além de PDF e HTML (zip, e-mail `.eml`/`.msg`, planilhas, Word) são listados como "não suportados" no relatório, mas não são lidos.
- A numeração de parágrafos que o SEI gera por CSS no HTML não é reconstruída.
- Velocidade: o OCR leva cerca de 3 segundos por página em cada núcleo. Os PDFs são divididos em lotes de 4 páginas entre os núcleos, então um PDF grande não ocupa um núcleo só. Centenas de páginas escaneadas ainda levam tempo: deixe processando.
- Página muito grande (planta, mapa) é lida com resolução reduzida (lado maior de até 7.000 px), e o relatório avisa.

## Desenvolvimento

```
uv sync            # inclui pytest e fpdf2
uv run pytest      # 22 testes, incluindo OCR real de PDF escaneado (exige tesseract com 'por')
```
