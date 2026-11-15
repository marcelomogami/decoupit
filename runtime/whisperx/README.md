# Runtime WhisperX

Este projeto `uv` mantém as dependências pesadas da transcrição fora do
ambiente principal do DecoupIt.

Para materializar o ambiente fixado:

```console
uv sync --project runtime/whisperx --frozen
```

Em uma árvore de desenvolvimento, o DecoupIt encontra automaticamente
`runtime/whisperx/.venv/bin/python`. Em uma instalação externa, o executável
pode ser informado em `DECOUPIT_WHISPERX_PYTHON`.

O alinhador não é baixado durante um job. O arquivo
`wav2vec2_fairseq_base_ls960_asr_ls960.pth`, com SHA-256
`488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`, deve
estar em `runtime/whisperx/models` na árvore de desenvolvimento, em
`~/.local/share/decoupit/models/whisperx` numa instalação externa ou no
diretório indicado por `DECOUPIT_WHISPERX_ALIGN_MODEL_DIR`.
