# Changelog

Todas as mudanças relevantes do DecoupIt serão documentadas neste arquivo.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/), com
versões de desenvolvimento compatíveis com a especificação de empacotamento do
Python.

## [Não lançado]

### Adicionado

- Pipeline WhisperX com Faster Whisper `medium`, VAD do pyannote e alinhamento
  fonético, usando chunks de dez segundos e timestamps em microssegundos.
- Runtime de IA separado e reproduzível, com PyTorch, CUDA, WhisperX e suas
  dependências fixados sem contaminar o ambiente principal.
- Perfil reproduzível com revisão exata do modelo e versões das bibliotecas
  registradas junto ao JSON bruto.
- Job persistente de transcrição com limites de 8 GiB de memória, 2 GiB de swap
  quatro CPUs e duas horas.
- Tabelas separadas para runs, segmentos e palavras, preservando também o JSON
  bruto em arquivo durável.
- Saídas anterior e posterior ao alinhamento preservadas no mesmo JSON, com os
  timestamps refinados usados pela interface e pelo SQLite.
- Endpoints para enfileirar e consultar a transcrição atual.
- Logs locais de jobs com diagnóstico incorporado ao estado de falha.
- Endpoint de conteúdo da transcrição por identificador interno.
- Transcript sincronizado ao lado do player, com destaque da palavra ativa e
  acompanhamento automático do trecho em reprodução.
- Busca local na transcrição, sem distinção de maiúsculas ou acentos, com
  navegação circular entre ocorrências e suporte a frases.
- Navegação do player ao clicar numa palavra ou selecionar um resultado, sem
  iniciar a reprodução automaticamente.
- Exportação SRT por download na tela de revisão, reagrupando palavras
  alinhadas por pausa, pontuação, duração e tamanho, com cues de até duas
  linhas.

### Alterado

- O planejamento consolida transcrição e alinhamento num único pipeline
  WhisperX isolado após as provas encontrarem erros grandes nos timestamps e
  confirmarem que o perfil com chunks de dez segundos cabe na GPU e recupera
  falas omitidas sem alterar o conteúdo reconhecido no controle com fala
  simples; a divisão dos cues foi implementada como etapa determinística
  separada.
- A integração direta com Faster Whisper foi substituída pelo pipeline
  WhisperX, mantendo a API, a persistência e a tela de revisão existentes.
- As dependências pesadas de IA saíram do ambiente principal e passaram para
  um projeto `uv` próprio.

### Corrigido

- Resolução do modelo local independente do `XDG_CACHE_HOME` usado pelos dados
  descartáveis do DecoupIt.
- Resolução do executável do ambiente virtual sem seguir o link simbólico até
  o Python base.

### Segurança

- A integração usa somente os modelos presentes no cache local, verifica o
  SHA-256 do alinhador e não inicia download durante uma transcrição.

## [0.2.0] - 2026-11-15

### Adicionado

- Cadastro somente leitura de vídeos brutos por caminho absoluto.
- Inspeção com `ffprobe`, persistindo identidade, streams, duração, resolução,
  codecs e classificação inicial da taxa de quadros.
- Backup automático do SQLite antes de aplicar migrações pendentes em bancos
  existentes.
- Job de normalização para H.264 CFR 30 com NVENC, validação por `ffprobe` e
  publicação por renomeação atômica.
- Endpoints para enfileirar a normalização, acompanhar o job e consultar a
  mídia de edição produzida.
- Limites de 2 GiB de memória, 1 GiB de swap, duas horas e uma normalização
  ativa por vez.
- Waveform JSON compacto gerado em fluxo diretamente da mídia normalizada, sem
  persistir um arquivo de áudio intermediário.
- Endpoints para enfileirar, consultar e obter os dados do waveform por
  identificador interno.
- Página local de revisão da mídia normalizada com player HTML5.
- Entrega de vídeo por identificador interno com suporte a requisições HTTP
  parciais para reprodução e busca.
- Waveform interativo na tela de revisão, com playhead sincronizado, busca por
  clique e avanço ou recuo de um quadro pelas setas.
- Conversões canônicas e testadas entre timestamps inteiros e quadros CFR 30.

### Alterado

- O planejamento deixou de prever áudio intermediário obrigatório. Faster
  Whisper e o waveform usarão inicialmente o áudio contido no MP4 normalizado;
  um cache separado só será criado se medições futuras justificarem o custo.
- O proxy de revisão permanece desabilitado após a mídia normalizada 1080p
  reproduzir e buscar corretamente no Chrome. A decisão será reavaliada com
  vídeos longos.

### Segurança

- A identidade do vídeo bruto é revalidada imediatamente antes da conversão.
- Um arquivo parcial nunca é publicado como mídia de edição válida.

## [0.1.0] - 2026-11-15

### Adicionado

- Estrutura inicial de empacotamento Python com versão `0.1.0.dev0`.
- Ambiente fixado em Python 3.12.8.
- Configuração de testes com pytest.
- Configuração de lint e formatação com Ruff.
- Política de versionamento e changelog desde o início do desenvolvimento.
- Aplicação FastAPI mínima com página de estado e endpoint de saúde.
- Comando `decoupit` limitado a `127.0.0.1`, com porta configurável.
- Resolução e criação dos diretórios de dados e cache conforme o padrão XDG.
- Testes de integração HTTP, segurança de host, CLI e diretórios locais.
- Banco SQLite inicial com tabela de projetos e migrações incorporadas ao
  pacote.
- Histórico de migrações com versão, nome e checksum para detectar alterações
  incompatíveis em migrações já aplicadas.
- Contrato persistente de jobs, com estados, regras de transição e recuperação
  após interrupção.
- Worker de execução única com tomada atômica da fila, subprocesso em grupo
  próprio, cancelamento da árvore e registro de sucesso ou falha.
- API local para criar e listar projetos vazios com persistência entre
  reinicializações.

### Alterado

- Documentação revisada para usar uma mídia de edição CFR 30 como referência
  canônica de quadros.
- README traduzido para português do Brasil.
- Dependências reproduzíveis adicionadas para FastAPI, Uvicorn e o cliente de
  testes HTTPX2.

### Segurança

- Requisições com cabeçalho `Host` fora de `localhost`, `127.0.0.1` e do host
  interno de testes são rejeitadas.
- Requisições de escrita com `Origin` diferente da origem local são rejeitadas.

[Não lançado]: https://github.com/marcelomogami/decoupit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/marcelomogami/decoupit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/marcelomogami/decoupit/releases/tag/v0.1.0
