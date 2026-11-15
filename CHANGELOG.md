# Changelog

Todas as mudanças relevantes do DecoupIt serão documentadas neste arquivo.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/), com
versões de desenvolvimento compatíveis com a especificação de empacotamento do
Python.

## [Não lançado]

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

[Não lançado]: https://github.com/marcelomogami/decoupit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/marcelomogami/decoupit/releases/tag/v0.1.0
