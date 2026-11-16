# DecoupIt

O DecoupIt é uma ferramenta local de pré-edição e revisão de vídeos. Seu
objetivo é preparar gravações longas antes da edição manual no Kdenlive.

## Estado

O planejamento inicial e a fundação técnica estão concluídos. Já existem o
pacote Python, o ambiente reproduzível, a aplicação web local, persistência
SQLite, projetos vazios, cadastro somente leitura dos brutos e normalização
CFR 30 pelo worker. A página inicial de operação ainda não existe, mas a tela
de revisão já reproduz o vídeo, mostra o waveform, acompanha tempo e quadros e
oferece uma transcrição pesquisável.

Versão de desenvolvimento atual: `0.4.0.dev0`. A fundação `0.1.0`, a
ingestão e normalização `0.2.0` e a transcrição navegável `0.3.0` estão
concluídas; a revisão manual persistente está em desenvolvimento. As mudanças
são registradas no [CHANGELOG.md](CHANGELOG.md).

Já é possível cadastrar um vídeo bruto por caminho absoluto em um projeto. O
DecoupIt consulta `ffprobe`, registra a identidade e os metadados do arquivo e
classifica inicialmente a taxa de quadros sem copiar nem alterar o bruto. A
normalização CFR 30 já pode ser enfileirada pela API e produz uma mídia de
edição validada antes da publicação. O waveform compacto é gerado diretamente
desse MP4, sem criar uma cópia de áudio separada.

## Objetivo

O DecoupIt deve reduzir o trabalho repetitivo anterior à edição criativa:

- normalizar vídeos VFR do celular para uma mídia de edição CFR 30;
- gerar um proxy leve para revisão quando ele for necessário;
- produzir uma transcrição pesquisável e sincronizada;
- identificar assuntos e tentativas repetidas;
- sugerir takes principais e alternativas;
- sinalizar pausas longas, frases interrompidas, tosses e outros eventos;
- classificar intervalos como principal, alternativa, blooper ou descarte;
- exportar legendas, relatórios e marcadores para o Kdenlive.

O fluxo esperado é:

```text
vídeo bruto VFR
  -> mídia de edição CFR 30
  -> análise e revisão local no DecoupIt
  -> SRT, CSV e marcadores de clipe
  -> edição precisa e renderização final no Kdenlive
```

## Limites do produto

O DecoupIt não pretende substituir um editor não linear. Ele não oferecerá
timeline avançada, efeitos, correção de cor, música, títulos, transições ou
renderização final.

Toda decisão automática permanecerá revisável. O vídeo bruto será tratado como
somente leitura. A mídia normalizada e os demais artefatos derivados serão
recriáveis.

## Arquitetura planejada

- Python 3.12 em ambiente isolado;
- FastAPI vinculado apenas ao computador local;
- SQLite para estado dos projetos e decisões de revisão;
- HTML renderizado pelo servidor com JavaScript mínimo;
- FFmpeg e ffprobe para normalização e processamento de mídia;
- NVIDIA NVENC, após validação do perfil;
- WhisperX em ambiente isolado para transcrição local com backend Faster
  Whisper e refinamento fonético dos timestamps;
- integração com o Kdenlive por SRT, CSV e marcadores JSON ligados ao clipe.

Processamentos longos serão executados fora do processo web, com limites
conservadores de memória, swap e concorrência.

## Execução local

Com `uv` instalado:

```bash
uv sync
uv sync --project runtime/whisperx --frozen
uv run decoupit
```

A página de estado fica disponível em <http://127.0.0.1:8000>. O servidor
aceita conexões apenas pela interface local. Outra porta pode ser escolhida com
`uv run decoupit --port 8123`.

O modelo fonético do alinhador é instalado separadamente e verificado por
SHA-256. As opções de localização estão em
[`runtime/whisperx/README.md`](runtime/whisperx/README.md). Nenhum modelo é
baixado durante um job.

Os dados duráveis ficam em `${XDG_DATA_HOME:-~/.local/share}/decoupit` e o
cache em `${XDG_CACHE_HOME:-~/.cache}/decoupit`. Na primeira inicialização, o
DecoupIt cria `decoupit.sqlite3` e aplica as migrações pendentes. O schema atual
permite criar e listar projetos vazios por `POST /api/projects` e
`GET /api/projects`. Edição e arquivamento ainda não foram implementados.

Vídeos brutos podem ser cadastrados por
`POST /api/projects/{project_id}/sources` e listados por
`GET /api/projects/{project_id}/sources`. O corpo de cadastro usa
`{"path":"/caminho/absoluto/video.mp4"}`.

A fila persistente possui estados, recuperação e um worker mínimo em processo
separado. O job `media.normalize_cfr30` executa FFmpeg com NVENC em um escopo
do systemd limitado a 2 GiB de memória, 1 GiB de swap e duas horas. Um lock
local limita a normalização a um vídeo por vez. O worker processa um job com:

```bash
uv run decoupit-worker --once
```

A conversão é solicitada por
`POST /api/projects/{project_id}/sources/{source_id}/normalization`. O estado é
consultado em `GET /api/jobs/{job_id}` e, após o sucesso, o artefato fica em
`GET /api/projects/{project_id}/sources/{source_id}/normalization`.

O waveform é solicitado por
`POST /api/projects/{project_id}/sources/{source_id}/waveform`. Seus metadados
ficam no `GET` do mesmo endereço, e os picos são servidos por identificador
interno em `GET /api/waveforms/{waveform_id}/data`. O artefato fica no cache e
pode ser recriado; nenhum arquivo de áudio intermediário é persistido.

A mídia normalizada pode ser revisada em
`GET /projects/{project_id}/sources/{source_id}/review`. O vídeo é servido por
identificador interno com suporte a requisições parciais, permitindo reprodução
e busca sem expor caminhos locais na URL. A amostra 1080p normalizada tocou e
buscou corretamente no Chrome, então um proxy separado permanece desabilitado
até que um vídeo longo demonstre necessidade real.

Na revisão, o waveform permite buscar por clique e avançar ou recuar um quadro
CFR 30 com as setas quando está focado. O contador usa quadros começando em
zero e exibe também o tempo correspondente.

A transcrição executa um pipeline WhisperX isolado com Faster Whisper
`medium`, VAD e alinhamento fonético na GPU. O worker preserva no JSON a saída
anterior e posterior ao alinhamento e persiste os timestamps refinados no
SQLite, sem baixar modelos silenciosamente. A tela de revisão mostra o
transcript ao lado do vídeo e destaca a palavra correspondente ao tempo atual.
Cada palavra pode ser clicada para levar o player ao seu início sem começar a
reprodução. A busca ignora maiúsculas, minúsculas e acentos, aceita frases e
permite navegar pelas ocorrências anteriores e seguintes. Quando a transcrição
está disponível, a mesma tela oferece o download de um SRT compatível com o
Kdenlive. Os cues são formados a partir das palavras alinhadas e não dos chunks
internos usados pelo WhisperX.

A revisão manual em desenvolvimento já permite marcar entrada e saída no
player, persistir o intervalo em quadros CFR 30, ajustar os dois limites e
classificá-lo como principal, alternativa, blooper ou descarte. A lista pode
ser retomada depois de fechar a página, e cada intervalo pode ser ouvido com
três segundos de contexto antes e depois.

## Privacidade

O DecoupIt será uma ferramenta pessoal e local. Vídeos, áudios, transcrições e
decisões permanecerão no computador. A primeira versão não dependerá de serviço
em nuvem nem terá telemetria.
