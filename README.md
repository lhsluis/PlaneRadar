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
| Polling | `5` segundos |

```powershell
python app.py
```

Para definir uma área e um intervalo personalizados:

```powershell
python app.py [latitude] [longitude] [distancia] [polling]
```

Exemplo:

```powershell
python app.py 41.179739 -8.671769 2 10
```

O polling deve ser um número inteiro de pelo menos 3 segundos. A distância aceita pela API é de até 250 milhas náuticas.

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

Para alterar a localização e o polling do container, edite as variáveis `PLANE_RADAR_LAT`, `PLANE_RADAR_LON`, `PLANE_RADAR_DISTANCE` e `PLANE_RADAR_POLLING` no `docker-compose.yml`. O polling deve ser inteiro e ter pelo menos 3 segundos.

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

As duas interfaces oferecem:

- Idiomas `pt-BR` e `en-US`.
- Alteração de latitude, longitude e distância.
- Polling configurável no início do servidor.
- Dados de companhia aérea, origem e destino por callsign.

Na página desktop, clicar em uma aeronave fixa o rastreamento nela. Sem seleção manual, a aeronave mais próxima do centro é rastreada.

## APIs internas

```text
GET /api/aircraft?lat={lat}&lon={lon}&dist={dist}
GET /api/flight-info?callsign={callsign}
GET /api/location?lat={lat}&lon={lon}&localityLanguage={pt|en}
```

- `/api/aircraft` consulta o endpoint v3 do adsb.fi.
- `/api/flight-info` consulta o ADSBdb pelo callsign retornado pela API ADS-B e mantém cache no servidor por 15 minutos.
- `/api/location` consulta o reverse geocoding da API BDC. A consulta ocorre no carregamento e quando latitude, longitude ou idioma mudam, não a cada refresh de aeronaves.

O polling ocorre no navegador, portanto o servidor não consulta as APIs quando não há páginas abertas.

## Uso das APIs externas

O endpoint público do adsb.fi possui limite de uma requisição por segundo e é destinado a uso pessoal e não comercial. O projeto atualiza aeronaves no mínimo a cada 3 segundos, conforme o parâmetro informado, e mantém o enriquecimento de callsigns em cache. Consulte os [termos do adsb.fi](https://github.com/adsbfi/opendata/blob/main/README.md), os [termos do ADSBdb](https://www.adsbdb.com/) e as condições dos demais fornecedores antes de publicar ou distribuir a aplicação.

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
