"""Termos usados na triagem. EDITÁVEL pelo analista.

Os padrões são aplicados ao texto em minúsculas e SEM acentos (escreva "licitacao", não
"licitação"). Cada termo tem um peso: 1 = fraco (aparece em documentos lícitos),
3-4 = forte (raramente aparece fora de contexto colusivo).

A triagem só PRIORIZA leitura. Não classifica condutas nem substitui a análise.
Alterar esta lista muda a pontuação; o hash da lista fica registrado em analise/triagem.json.
"""

CATEGORIAS = {
    "Licitação: cobertura, rodízio, supressão": [
        (r"\bpropostas? de cobertura\b", 4),
        (r"\bpropostas? (ficticias?|de fachada|figurativas?|pro forma)\b", 4),
        (r"\brodizio\b", 3),
        (r"\brevezamento\b", 3),
        (r"\b(agora e a sua vez|sua vez|nossa vez|vez de voces|vez deles)\b", 2),
        (r"\bdeixa(r|mos)? (voces |eles |a gente |o outro )?ganhar\b", 4),
        (r"\bnao (vamos |iremos |vou )?(participar|disputar|concorrer|cotar)\b", 3),
        (r"\bdesist(ir|imos|encia|iu)\b", 2),
        (r"\bcobertura\b", 1),
        (r"\b(compensac\w+|subcontrat\w+)\b", 1),
        (r"\b(licitac\w+|pregao|pregoes|certame|edital|concorrencia publica)\b", 1),
    ],
    "Fixação de preços e condições": [
        (r"\bfix(ar|amos|acao|ado|ados) (o |os |de )?precos?\b", 4),
        (r"\btabela (de precos?|unica|comum)\b", 3),
        (r"\bpreco (minimo|combinado|acertado|de referencia do grupo)\b", 3),
        (r"\b(manter|segurar|nao baixar|nao reduzir) (o |os |nosso |nossos )?precos?\b", 3),
        (r"\b(reajuste|aumento) (conjunto|combinado|de todos|linear)\b", 3),
        (r"\bdesconto maximo\b", 2),
        (r"\bmargem\b", 1),
        (r"\breajuste\b", 1),
    ],
    "Divisão de mercado, clientes ou lotes": [
        (r"\bdivisao (de |do |dos |das )?(mercado|clientes|regioes|territorios?|lotes|contratos|obras)\b", 4),
        (r"\bdividir (o |os |as )?(mercado|clientes|lotes|regioes|contratos|obras)\b", 4),
        (r"\bnao (atender|atacar|entrar|prospectar) (no|na|nos|nas|o|a|os|as) (cliente|regiao|territorio|area)\w*\b", 3),
        (r"\b(cliente|regiao|area|lote) (de voces|deles|da outra|do outro|dele)\b", 2),
        (r"\bterritori\w+\b", 1),
    ],
    "Troca de informação sensível": [
        (r"\bnossa proposta (sera|vai ser|fica|ficara)\b", 3),
        (r"\bvamos (entrar|cotar|ofertar|dar lance) com\b", 3),
        (r"\bqual (vai ser |sera )?(o |a )?(seu |sua |teu |tua )?(preco|proposta|lance|desconto)\b", 3),
        (r"\b(planilha|estrutura|composicao) de custos?\b", 2),
        (r"\b(capacidade|volume|carteira) (de|dos) clientes?\b", 1),
    ],
    "Coordenação entre concorrentes": [
        (r"\bconforme (combinado|acertado|conversado|alinhado)\b", 3),
        (r"\b(conluio|cartel|clube)\b", 3),
        (r"\b(combinad|acertad)[oa]s?\b", 2),
        (r"\b(alinhad[oa]s?|alinhamento|alinhar)\b", 1),
        (r"\b(acordo|ajuste|entendimento) entre\b", 2),
        (r"\bconcorrentes?\b", 1),
    ],
    "Sigilo e ocultação": [
        (r"\b(apague|apagar|delete|deletar|destrua|destruir) (este|esse|essa|esta|a|o)\b", 4),
        (r"\bnao (comente|comentar|repasse|repassar|encaminhe|encaminhar|divulgue)\b", 2),
        (r"\bnao (por|pelo) e-?mail\b", 3),
        (r"\b(por|pelo) (telefone|celular|whats\w*|zap|signal|telegram)\b", 2),
        (r"\b(e-?mail|celular|telefone|numero) (pessoal|particular)\b", 2),
        (r"\b(pessoalmente|ao vivo|fora do escritorio)\b", 1),
        (r"\b(confidencial|sigiloso|reservado)\b", 1),
    ],
    "Encontros e contatos": [
        (r"\breuni(ao|oes|r|mos|ram)\b", 1),
        (r"\b(cafe|almoco|jantar|happy hour|encontro)\b", 1),
        (r"\b(associacao|sindicato|entidade de classe)\b", 1),
    ],
}

# Bônus estruturais (não dependem de palavras).
BONUS_CNPJS_DISTINTOS = 3       # documento cita 2+ CNPJs diferentes (possíveis concorrentes)
BONUS_DOMINIOS_DISTINTOS = 2    # e-mails de 2+ domínios corporativos diferentes
MAX_OCORRENCIAS_POR_TERMO = 5   # evita que um termo repetido domine a pontuação

DOMINIOS_GENERICOS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.br", "uol.com.br",
    "bol.com.br", "terra.com.br", "icloud.com", "live.com", "msn.com", "ig.com.br",
}
