# DecoupIt

O DecoupIt é uma ferramenta local de pré-edição e revisão de vídeos. Seu
objetivo é preparar gravações longas antes da edição manual no Kdenlive.

## Estado

O planejamento inicial está concluído e a fundação técnica começou. Já existem
o pacote Python, o ambiente reproduzível e as verificações básicas, mas ainda
não há aplicação executável nem interface web.

Versão de desenvolvimento atual: `0.1.0.dev0`. As mudanças planejadas e
entregues são registradas no [CHANGELOG.md](CHANGELOG.md).

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
- Faster Whisper para transcrição local;
- WhisperX opcional quando a precisão medida justificar seu custo;
- integração com o Kdenlive por SRT, CSV e marcadores JSON ligados ao clipe.

Processamentos longos serão executados fora do processo web, com limites
conservadores de memória, swap e concorrência.

## Privacidade

O DecoupIt será uma ferramenta pessoal e local. Vídeos, áudios, transcrições e
decisões permanecerão no computador. A primeira versão não dependerá de serviço
em nuvem nem terá telemetria.
