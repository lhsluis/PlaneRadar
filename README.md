# PlaneRadar

Tracker local de aeronaves próximas usando Python, Flask, Jinja2, JavaScript/CSS vanilla e as APIs públicas [adsb.fi](https://adsb.fi/), [ADSBdb](https://www.adsbdb.com/) e [API BDC](https://api-bdc.io/).

## Requisitos

- Python 3.10 ou superior
- Acesso à internet para consultar os serviços externos

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se o PowerShell bloquear a ativação:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Executar

Sem argumentos, o servidor usa:

| Parâmetro | Padrão |
|---|---:|
| Latitude | `-21.805684` |
| Longitude | `-48.139653` |
| Distância | `25` NM |
| Polling | `10` segundos |
| Chave da API de logos | vazia (opcional) |

```powershell
python app.py
```

Para definir uma área e um intervalo personalizados:

```powershell
python app.py [latitude] [longitude] [distancia] [polling] [airline_logo_api_key]
```

Exemplo:

```powershell
python app.py -21.805684 -48.139653 25 10
```

O polling deve ser um número inteiro de pelo menos 3 segundos. A distância aceita pela API é de até 250 milhas náuticas.

A chave da API de logos é opcional e deve ser informada somente como o último argumento. A chave pode ser obtida em https://airline.logostream.dev/pricing a partir do free tier. Sem a chave, `airline_logo` retorna `null`.

Exemplo standalone usando uma chave fictícia:

```powershell
python app.py -21.805684 -48.139653 25 10 DUMMY-AIRLINE-LOGO-API-KEY
```

O Flask escuta em `0.0.0.0`, permitindo acesso externo:

- Computador local: `http://127.0.0.1:5000`
- Outro dispositivo na mesma rede: `http://IP_DO_SERVIDOR:5000`

Use `FLASK_PORT` para alterar a porta e `FLASK_DEBUG=true` para ativar o modo debug:

```powershell
$env:FLASK_PORT = "8080"
$env:FLASK_DEBUG = "true"
python app.py
```

## Deploy com Docker e Gunicorn

O projeto inclui `Dockerfile` e `docker-compose.yml`. Para iniciar em produção:

```powershell
docker compose up -d --build
```

A aplicação ficará disponível em `http://IP_DO_SERVIDOR:5000`. O container usa Gunicorn com um worker e quatro threads, roda como usuário sem privilégios e reinicia automaticamente.

O Docker Compose monta o volume persistente `planeradar-data` em `/data` e grava o SQLite em `/data/planeradar-cache.sqlite3`. No Synology, o container roda com `dockerlimited` (UID `1030`) e `dockergroup` (GID `65536`), conforme a configuração do host. Assim, os caches de informações de voo e de silhuetas, inclusive ausências de silhueta, sobrevivem à recriação do container. O volume pode ser removido explicitamente com `docker compose down -v`.

No Synology Container Manager, prefira esse volume nomeado. Se usar uma pasta compartilhada como bind mount em `/data`, conceda permissão de leitura e escrita para o UID `1030` e GID `65536` nessa pasta antes de iniciar o projeto; caso contrário, o Gunicorn falhará com `sqlite3.OperationalError: unable to open database file`.

### Usuário do container e Portainer

O `docker-compose.yml` inclui `user: "1030:65536"` para executar o serviço com `dockerlimited`/`dockergroup` no Synology. Em Portainer ou em outro ambiente Docker, esses IDs podem não existir ou não ter acesso ao volume. Nesse caso, remova ou substitua essa configuração com um arquivo override, e conceda ao usuário escolhido permissão de leitura e escrita em `/data`. Sem essa permissão, o SQLite não conseguirá ser aberto.

Exemplo de override para um ambiente que use outro UID/GID:

```yaml
services:
  planeradar:
    user: "UID:GID"
```

Para alterar a localização, o polling e, opcionalmente, a chave de logos do container, use as variáveis `PLANE_RADAR_LAT`, `PLANE_RADAR_LON`, `PLANE_RADAR_DISTANCE`, `PLANE_RADAR_POLLING` e `PLANE_RADAR_AIRLINE_LOGO_API_KEY`. O polling deve ser inteiro e ter pelo menos 3 segundos. A variável de chave fica vazia por padrão; em produção, forneça-a por variável de ambiente ou secret, sem gravá-la no repositório. Para documentação ou testes locais, use uma chave fictícia como `DUMMY-AIRLINE-LOGO-API-KEY`.

Para acompanhar os logs:

```powershell
docker compose logs -f planeradar
```

Para parar:

```powershell
docker compose down
```

## Interfaces

- `/` — radar completo, seleção de aeronave e tabela enriquecida.
- `/mobile` — versão otimizada para dispositivos móveis, somente com a tabela.
- Na versão mobile, o botão “Rastrear minha posição” pode preencher latitude e longitude usando a geolocalização do navegador. O recurso depende da permissão do usuário e de um contexto seguro (HTTPS ou localhost).

As duas interfaces oferecem:

- Idiomas `pt-BR` e `en-US`.
- Alteração de latitude, longitude e distância.
- Polling configurável no início do servidor.
- Dados de companhia aérea, origem e destino por callsign.
- Silhueta da aeronave rastreada usando o código `t` e os SVGs do repositório [pw-silhouettes](https://github.com/plane-watch/pw-silhouettes).
- Silhuetas são servidas por `/api/silhouette/{t}` (com ou sem sufixo `.svg`) e ficam em cache no servidor, inclusive tipos inexistentes, para evitar consultas repetidas ao GitHub. Em Docker, esse cache é persistido no SQLite do volume `planeradar-data`.
- Contagem anônima de sessões ativas no footer, atualizada por heartbeat e exibida como “sessões olhando lá pra cima!” ou “sessions looking up there!”.

Na página desktop, clicar em uma aeronave fixa o rastreamento nela. Sem seleção manual, a aeronave mais próxima do centro é rastreada.

## APIs internas

```text
GET /api/aircraft?lat={lat}&lon={lon}&dist={dist}
GET /api/nearest-aircraft?lat={lat}&lon={lon}&dist={dist}
GET /api/flight-info?callsign={callsign}
GET /api/airline-logo/{icao}
GET /api/location?lat={lat}&lon={lon}&localityLanguage={pt|en}
POST /api/presence
```

- `/api/aircraft` consulta o endpoint v3 do adsb.fi. O backend reserva os slots das consultas com intervalo mínimo de 2 segundos, evitando colisões quando várias sessões estão abertas ao mesmo tempo.
- `/api/nearest-aircraft` retorna a aeronave mais próxima, todos os dados ADS-B exibidos nas tabelas, o enriquecimento de companhia/rota em `flight_info`, os links da silhueta em `silhouette` e do logo da companhia em `airline_logo`, além de `location` com cidade, subdivisão principal e país. `silhouette` é `null` quando o tipo da aeronave não possui arquivo correspondente. O logo é buscado na Logostream somente quando não está no cache SQLite e servido pelo endpoint interno `/api/airline-logo/{icao}`.
- `/api/flight-info` consulta o ADSBdb pelo callsign retornado pela API ADS-B e mantém cache no servidor por 15 minutos; em Docker, o cache é persistido no SQLite do volume `planeradar-data`.
- `/api/location` consulta o reverse geocoding da API BDC. A consulta ocorre no carregamento e quando latitude, longitude ou idioma mudam, não a cada refresh de aeronaves.
- `/api/presence` registra um identificador anônimo do navegador e retorna a quantidade de sessões ativas.

O polling ocorre no navegador, portanto o servidor não consulta as APIs quando não há páginas abertas.
O contador de usuários considera ativos os navegadores que enviaram heartbeat nos últimos 45 segundos. O identificador é anônimo e não armazena endereço IP. Como o contador fica em memória, em deployments com múltiplos workers ou réplicas ele deve ser movido para um armazenamento compartilhado.

O caminho do banco de cache pode ser alterado com `PLANE_RADAR_CACHE_DB`. O cache de informações de voo expira em 15 minutos, o cache de silhuetas expira em 24 horas e o cache de logos expira em 7 dias. O contador de presença e o limitador de requisições ao adsb.fi continuam em memória por representarem estado temporário do processo.

## Uso das APIs externas

O endpoint público do adsb.fi possui limite de uma requisição por segundo e é destinado a uso pessoal e não comercial. Além do intervalo configurado no navegador, o servidor aplica um intervalo mínimo global de 2 segundos entre o início das consultas ao adsb.fi. A configuração de produção usa um worker Gunicorn para que esse limitador seja compartilhado por todas as threads; ao escalar para múltiplos workers ou réplicas, use um limitador compartilhado externo, como Redis. Consulte os [termos do adsb.fi](https://github.com/adsbfi/opendata/blob/main/README.md), os [termos do ADSBdb](https://www.adsbdb.com/) e as condições dos demais fornecedores antes de publicar ou distribuir a aplicação.

## Estrutura

```text
app.py
requirements.txt
templates/
  index.html
  mobile.html
static/
  app.js
  mobile.js
  styles.css
```
