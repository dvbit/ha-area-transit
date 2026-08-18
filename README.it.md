<p align="center">
  <img src="icon.png" alt="Area Transit" width="128" height="128">
</p>

<h1 align="center">Area Transit</h1>

<p align="center">
  Rileva il passaggio di persone da un'area all'altra, con direzione, contatori
  e occupazione stimata — usando i sensori di movimento che hai già.
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS custom"></a>
  <img src="https://img.shields.io/badge/versione-1.1.0-blue.svg" alt="Versione 1.1.0">
  <img src="https://img.shields.io/badge/Home%20Assistant-2025.6%2B-41BDF5.svg" alt="Home Assistant 2025.6+">
</p>

> 🇬🇧 [Read this page in English](README.md) — 📄 [Specifica](SPEC.md)

## Cosa fa

Un **varco** è il confine tra due aree. Area Transit osserva i sensori attorno
a quel confine e registra un transito **solo se scattano nell'ordine giusto**,
entro una finestra di tempo configurabile:

```
             ┌──────────┐   ┌──────────┐
   Sensore   │ sensore  │   │ Sensore
   area A  ──┼─ confine ┼──▶│ area B
             └──────────┘   └──────────┘
      1°          2°             3°       →  transito A ➜ B
```

Il sensore di confine è opzionale, ma una volta configurato diventa
obbligatorio: senza il suo scatto la sequenza viene scartata. È proprio questo
che tiene lontani i falsi positivi.

I varchi contigui vengono concatenati: se qualcuno attraversa
`Ingresso ➜ Corridoio` e poco dopo `Corridoio ➜ Camera`, oltre ai due transiti
singoli viene segnalato un unico **percorso** `Ingresso ➜ Camera passando per
Corridoio`.

## Installazione

### HACS (consigliata)

1. HACS → ⋮ → **Repository personalizzati**
2. Repository `https://github.com/dvbit/ha-area-transit`, categoria **Integration**
3. Installa **Area Transit** e riavvia Home Assistant
4. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Area Transit**

### Manuale

Copia `custom_components/area_transit` nella cartella
`config/custom_components/` e riavvia Home Assistant.

## Configurazione

L'aggiunta dell'integrazione chiede solo la **finestra tra varchi**: il ritardo
massimo tra due transiti perché vengano considerati un unico percorso.

Poi aggiungi un varco alla volta dalla pagina dell'integrazione
(**Aggiungi varco**):

| Campo | Significato | Default |
| --- | --- | --- |
| Nome | Nome del dispositivo del varco | — |
| Area A / Area B | Le due aree collegate dal varco | — |
| Sensore di movimento in area A / B | Un `binary_sensor` per area, vicino al varco | — |
| Sensore di confine | Opzionale. **Obbligatorio nella sequenza se impostato** | — |
| Timeout sequenza | Tempo massimo tra il primo e l'ultimo sensore | 10 s |
| Tempo di attesa | Tempo in cui il varco ignora eventi dopo un transito | 5 s |

I varchi si possono modificare o rimuovere in qualsiasi momento:
l'integrazione si ricarica da sola.

## Entità

Per ogni varco (dispositivo = il varco):

| Entità | Esempio | Descrizione |
| --- | --- | --- |
| Ultimo transito | `sensor.varco_corridoio_ultimo_transito` | Timestamp dell'ultimo transito. Attributi: `direction`, `from_area`, `to_area`, `duration`, `sensors`, `boundary_used` |
| Direzione | `sensor.varco_corridoio_direzione` | `in_to_out` (A ➜ B) oppure `out_to_in` (B ➜ A) |
| Transiti da A a B | `sensor.varco_corridoio_transiti_da_a_a_b` | Contatore |
| Transiti da B ad A | `sensor.varco_corridoio_transiti_da_b_ad_a` | Contatore |

Per ogni area monitorata (dispositivo = l'area):

| Entità | Esempio | Descrizione |
| --- | --- | --- |
| Occupazione stimata | `sensor.soggiorno_occupazione_stimata` | Conteggio persone, `+1` in ingresso, `-1` in uscita, mai sotto zero |

Sul dispositivo unico **Area Transit Hub** (uno per config entry, aggrega l'attività di tutti i varchi):

| Entità | Esempio | Descrizione |
| --- | --- | --- |
| Ultimo percorso | `sensor.area_transit_hub_last_path` | Timestamp dell'ultimo percorso multi-varco completato. Attributi: `origin`, `destination`, `via`, `gates`, `duration` |
| Transiti totali | `sensor.area_transit_hub_total_transits` | Transiti registrati su tutti i varchi, indipendentemente dalla direzione |

Tutti i valori sopravvivono al riavvio di Home Assistant.

> Gli `entity_id` derivano dal nome del dispositivo e dalla lingua attiva al
> momento della creazione dell'entità: verificali in **Impostazioni →
> Dispositivi e servizi → Entità**.

## Servizi

```yaml
# Riallinea l'occupazione stimata di un'area
action: area_transit.reset_occupancy
target:
  entity_id: sensor.soggiorno_occupazione_stimata
data:
  value: 0

# Azzera contatori, ultimo transito e direzione di un varco
# (puntando al dispositivo del varco si azzerano tutte le sue entità)
action: area_transit.reset_counters
target:
  device_id: 1a2b3c4d5e6f
```

## Eventi

### `area_transit_transit`

```json
{
  "gate_id": "01JABCDEF...",
  "gate_name": "Varco corridoio",
  "direction": "in_to_out",
  "from_area_id": "ingresso",
  "from_area": "Ingresso",
  "to_area_id": "soggiorno",
  "to_area": "Soggiorno",
  "started": "2026-08-17T18:04:11.120000+00:00",
  "ended": "2026-08-17T18:04:13.480000+00:00",
  "duration": 2.36,
  "sensors": ["binary_sensor.ingresso_movimento", "binary_sensor.varco_confine", "binary_sensor.soggiorno_movimento"],
  "boundary_used": true
}
```

### `area_transit_path`

```json
{
  "origin_id": "ingresso",
  "origin": "Ingresso",
  "destination_id": "camera",
  "destination": "Camera",
  "via_ids": ["corridoio"],
  "via": ["Corridoio"],
  "gates": ["Varco ingresso", "Varco camera"],
  "started": "2026-08-17T18:04:11.120000+00:00",
  "ended": "2026-08-17T18:04:22.900000+00:00",
  "duration": 11.78,
  "transits": []
}
```

## Esempi di utilizzo

### Accendi la luce solo a chi *entra* nella stanza

```yaml
automation:
  - alias: "Luce soggiorno all'ingresso"
    triggers:
      - trigger: event
        event_type: area_transit_transit
        event_data:
          to_area_id: soggiorno
    actions:
      - action: light.turn_on
        target:
          entity_id: light.soggiorno
```

### Notifica il percorso ingresso → camera

```yaml
automation:
  - alias: "Dall'ingresso alla camera"
    triggers:
      - trigger: event
        event_type: area_transit_path
    conditions:
      - condition: template
        value_template: >
          {{ trigger.event.data.origin_id == 'ingresso'
             and trigger.event.data.destination_id == 'camera' }}
    actions:
      - action: notify.mobile_app_telefono
        data:
          message: >
            Qualcuno è passato da {{ trigger.event.data.origin }} a
            {{ trigger.event.data.destination }} tramite
            {{ trigger.event.data.via | join(', ') }}
            in {{ trigger.event.data.duration | round(1) }} s
```

### Spegni tutto quando un'area si svuota

```yaml
automation:
  - alias: "Studio vuoto"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.studio_occupazione_stimata
        below: 1
        for: "00:05:00"
    actions:
      - action: light.turn_off
        target:
          area_id: studio
```

### Riallineamento notturno delle stime

L'occupazione è una stima e nel tempo va in deriva (una finestra, un animale,
una sequenza persa). Un azzeramento giornaliero la riporta in riga:

```yaml
automation:
  - alias: "Azzeramento notturno occupazione"
    triggers:
      - trigger: time
        at: "04:00:00"
    actions:
      - action: area_transit.reset_occupancy
        target:
          entity_id:
            - sensor.soggiorno_occupazione_stimata
            - sensor.camera_occupazione_stimata
        data:
          value: 0
```

### Card per la dashboard

```yaml
type: entities
title: Varco corridoio
entities:
  - entity: sensor.varco_corridoio_ultimo_transito
  - entity: sensor.varco_corridoio_direzione
  - entity: sensor.varco_corridoio_transiti_da_a_a_b
  - entity: sensor.varco_corridoio_transiti_da_b_ad_a
  - entity: sensor.soggiorno_occupazione_stimata
```

## Consigli di posizionamento

* Orienta i due sensori di movimento **in direzioni opposte**, ciascuno sul
  proprio lato del varco, così una sola persona non può attivarli insieme.
* Riduci le sovrapposizioni di copertura: un sensore che vede entrambi i lati
  rompe l'ordine della sequenza.
* Se i PIR hanno un tempo di ritenuta lungo, tieni il timeout sequenza più alto
  di quel valore.
* Aggiungi il sensore di confine (contatto porta, barriera a infrarossi, zona
  mmWave) quando la precisione conta più della copertura.

## Diagnostica

Abilita il log di debug per vedere ogni passo della macchina a stati:

```yaml
logger:
  default: warning
  logs:
    custom_components.area_transit: debug
```

| Sintomo | Causa probabile |
| --- | --- |
| Nessun transito | Sensore di confine configurato ma che non scatta mai, oppure sensori che scattano insieme |
| `sequence discarded, expected ...` | Coperture sovrapposte o aree invertite |
| `sequence expired` | Timeout sequenza troppo corto per la distanza |
| Contatori che salgono il doppio | Tempo di attesa più corto della ritenuta del PIR |
| Occupazione in deriva | Normale per una stima: usa l'azzeramento notturno qui sopra |

## Licenza

MIT — vedi [LICENSE](LICENSE).
