# Deploy no Synology NAS

Este guia descreve o deploy do PlaneRadar no Synology usando `docker-compose.synology.yml`. O container escuta apenas em `127.0.0.1:${HTTP_PORT}` e o acesso externo passa pelo reverse proxy HTTPS do DSM. HTTPS é necessário para o PWA ser instalável.

## Primeira instalação

1. Clone o repositório:

   ```bash
   sudo mkdir -p /volume1/docker
   cd /volume1/docker
   sudo git clone https://github.com/lhsluis/PlaneRadar.git planeradar
   cd planeradar
   ```

2. Crie o `.env` a partir do exemplo e ajuste os valores:

   ```bash
   sudo cp .env.synology.example .env
   sudo vi .env
   ```

3. Crie a pasta de dados (cache SQLite) com o dono usado pelo container:

   ```bash
   sudo mkdir -p data
   sudo chown -R 1030:65536 data
   ```

4. Suba o projeto, escolhendo uma das opções:

   - **Script de deploy** (recomendado): `sudo python3 deploypipeline.py /volume1/docker/planeradar planeradar`
   - **Container Manager**: em *Projeto* > *Criar*, aponte o caminho para `/volume1/docker/planeradar` e selecione `docker-compose.synology.yml`.

5. Configure o reverse proxy HTTPS no DSM: *Painel de Controle* > *Portal de Login* > *Avançado* > *Proxy reverso*, com:

   - Origem: `HTTPS`, nome de host desejado, porta `443`.
   - Destino: `HTTP`, `localhost`, porta igual a `HTTP_PORT` (padrão `5000`).

   Use um certificado válido para o nome de host (em *Segurança* > *Certificado* do DSM).

## Deploys seguintes

Dentro da pasta do projeto, rode o mesmo comando do script:

```bash
cd /volume1/docker/planeradar
sudo python3 deploypipeline.py /volume1/docker/planeradar planeradar
```

O script exige git limpo, faz `git pull`, reconstrói a imagem e reinicia os containers, aguardando ficarem `running` e `healthy` (timeout de 180 s). A opção `--skip-backup` não é necessária: o backup é pulado automaticamente porque o projeto não tem serviço `db`.

## Troubleshooting

- Ver logs:

  ```bash
  sudo docker compose -p planeradar -f docker-compose.synology.yml logs -f planeradar
  ```

- Status e healthcheck: `sudo docker ps --filter name=planeradar` (o status deve ser `healthy`). Teste direto no NAS: `curl -i http://127.0.0.1:5000/healthz` deve responder `200 ok`.
- `sqlite3.OperationalError: unable to open database file`: a pasta `data` não pertence a `1030:65536`. Corrija com `sudo chown -R 1030:65536 data`.
- Porta em uso: altere `HTTP_PORT` no `.env` e ajuste o destino do reverse proxy.
- Após alterar o `.env`, rode o deploy novamente para aplicar as mudanças.
- Logs ou containers não aparecem no Container Manager: confira se o projeto foi criado com o nome `planeradar`.
