# Open WebUI em host externo

O Open WebUI nao pertence ao deploy canonico do NanotechSoft. Ele deve rodar
em um host e em uma composicao Docker proprios. Os comandos `up.sh`, `down.sh`
e `update.sh` nao criam, atualizam, param nem removem o WebUI.

O Ollama continua opcionalmente no servidor NanotechSoft, no perfil Compose
`ai`, porque o Agent IA do RioB tambem o utiliza. Quando um WebUI externo
precisar acessar esse Ollama, publique a porta somente no IP Tailscale do
servidor:

```env
RB_OLLAMA_BIND=IP_TAILSCALE_DO_SERVIDOR
RB_OLLAMA_PORT=11434
```

Nunca use `0.0.0.0` para esse acesso. No host externo, configure
`OLLAMA_BASE_URL=http://IP_TAILSCALE_DO_SERVIDOR:11434` e mantenha o volume de
usuarios e conversas na propria composicao do WebUI.

## Validacao

1. No host externo, confirme `GET /health` do WebUI.
2. A partir do host externo, confirme `GET /api/tags` do Ollama pelo Tailscale.
3. Confira usuarios e conversas antes de remover o volume antigo.
4. Pare e remova o container antigo somente depois dessas verificacoes.
5. Mantenha backup do volume antigo ate concluir a validacao funcional.

Modelos do Ollama nao sao copiados nessa migracao: permanecem no servidor que
executa o perfil `ai`. O prototipo de roteador e seus volumes sao independentes
e nao devem ser alterados por essa operacao.

## Instalacao MiniOS atual

- host do WebUI: `192.168.200.184:3000`
- imagem homologada na migracao: `ghcr.io/open-webui/open-webui:v0.5.20`
- volume: `open_webui_external_data`
- Ollama: `100.72.18.123:11434` pela rede Tailscale
- politica de reinicio: `unless-stopped`

No MiniOS, `/dev/sda1` possui 449 GB e sustenta a raiz persistente; o ext4 deve
ocupar toda essa particao. `/dev/sda3` possui outros 482 GB e o Docker usa
`/media/renan/PARTICAO2/docker-data` nesse segundo ext4. Como o sistema recria
`/etc/fstab` no boot, a montagem persistente de `/dev/sda3` e
feita pela unidade `media-renan-PARTICAO2.mount`. O drop-in
`docker.service.d/storage.conf` exige essa unidade antes de iniciar o Docker.
Sem essa dependencia, o Docker pode subir primeiro sobre a raiz AUFS, cair no
driver `vfs` e aparentar que imagens, volumes e containers desapareceram.

Validacao depois de reiniciar:

```bash
findmnt /media/renan/PARTICAO2
docker info --format 'root={{.DockerRootDir}} driver={{.Driver}}'
docker ps --filter name=open-webui
curl --fail http://192.168.200.184:3000/health
```

O resultado esperado e `driver=overlay2`, o data root no disco grande e
`{"status":true}` no endpoint de saude.

Se `lsblk` mostrar `/dev/sda1` com centenas de GB, mas `df -h /` mostrar apenas
cerca de 57 GB, a particao ja foi ampliada e apenas o ext4 ficou no tamanho
antigo. Execute `e2fsck` somente com `/dev/sda1` desmontado (por exemplo, no
boot oficial `Copiar para RAM`) e depois `resize2fs /dev/sda1`. Nunca execute o
reparo forcado enquanto essa particao estiver servindo como camada persistente
do sistema.
