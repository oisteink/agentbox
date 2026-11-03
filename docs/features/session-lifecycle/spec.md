# Kjøring og livssyklus

Status: brukeravklart kontrakt under videre gjennomgang av CLI-en.
Dette beskriver ønsket oppførsel, ikke dagens implementasjon.
Ingen implementasjon eller nye testløp startes mens brukerflyten diskuteres.

## Avklart

- Normal bruk starter nødvendige ressurser automatisk. Brukeren skal ikke
  henvises til en annen kommando når abx har informasjonen som trengs.
- `abx start CONFIG [--keep-running]` bygger image ved behov, oppretter eller
  starter miljøet og kjører miljøets konfigurerte kommando i terminalen.
- `abx exec CONFIG [--keep-running] -- KOMMANDO` har samme livssyklus, med
  en eksplisitt kommando. Interaktiv terminal velges automatisk når det passer.
  Pipet stdin skal videresendes uten TTY; stdout skal kunne omdirigeres.
- Hver kjøring rydder bare etter egen oppstart: stopp ved avslutning bare
  dersom denne kjøringen startet containeren og ikke fikk --keep-running.
  En container som allerede kjørte, skal fortsatt kjøre etter kommandoen.
- --keep-running lar containeren kjøre etter avsluttet kommando. Den stoppes
  eksplisitt med `abx stop NAVN`. Gjentatt bruk av flagget gir ingen teller
  eller ekstra eierskap.
- `persistent` gjelder containerlaget ved stopp, ikke om miljøet skal stå og
  kjøre. Standard er true: stopp beholder laget, hjemmet og innloggingen.
  Med false fjernes miljøets runtime-ressurser ved stopp.
- Et ikke-persistent miljø kan startes med --keep-running, brukes til flere
  kommandoer/økter i samme container og til slutt fjernes med stop.
- `abx run CONFIG` bruker alltid et nytt, separat midlertidig miljø og fjerner
  bare dette etter bruk. Et eksisterende miljø fra samme konfigurasjon berøres ikke.
- `abx remove NAVN` rydder både persistente og ikke-persistente miljøer, også
  kjørende. Allerede fjernede ressurser krever ingen handling.
- Stopp/fjerning sletter ikke miljøkonfigurasjon, prosjektfiler eller
  prosjektregistreringer. Fjerning av containerlaget sletter hjem/innlogging.
- `abx status` viser en tabell over alle konfigurerte miljøer, også dem som
  aldri er startet eller har fått containeren fjernet. Oversikten viser
  miljønavn, status (kjører/stoppet/ikke opprettet) og persistens.
- `abx status NAVN` viser detaljer for ett miljø: tilstand, persistens, image,
  prosjekter/mounts og nettverkstilganger, også uten opprettet container.
- `abx logs NAVN` viser siste utsnitt av agentloggen; `--proxy` velger
  proxyloggen. `-f` / `--follow` følger nye logghendelser fortløpende for
  begge loggtyper. Ctrl-C avslutter loggvisningen uten å stoppe miljøet.
- `abx validate CONFIG` kontrollerer miljøfilen uten oppstart. Menneskemodus
  viser en kort bekreftelse eller konkrete feil; `--json` gir strukturert
  resultat eller feil etter den felles utskriftskontrakten.

## Utskrift for mennesker og agenter

Status: felles føring avklart; detaljformat avklares under kommandogjennomgangen.

- Standardutskrift er for mennesker: tabeller for oversikter, lesbare detaljer
  og konkrete feilmeldinger der det passer kommandoen.
- `--json` gir strukturert utskrift for agenter. Både resultat og feil skal
  kunne forstås fra JSON uten tolking av mennesketekst eller exitkoder.
- I JSON-modus rapporteres håndterte feil i JSON med exitkode 0. Vanlig
  menneskemodus beholder exitkoder for feil.
- JSON-resultatet må skille entydig mellom suksess og feil og gi en stabil
  feilkategori samt forståelig forklaring. Det konkrete skjemaet er ikke valgt.
- Føringen gjelder på tvers av CLI-en. Utskrift avklares organisk for hver
  kommando; gjennomføringen samles etter at brukerflyten er ferdig diskutert.

## Åpent før implementasjon

- Shell er foreslått fjernet fordi start åpner konfigurert kommando.
  Endelig kommandoliste fastsettes i gjennomgangen.
- Samtidige kjøringer: hvordan hindre at en kjøring stopper en container
  mens en annen bruker den? Ingen teller eller sesjonsmekanisme er valgt.
  Avklar også --keep-running fra en annen kjøring mens oppstarteren er aktiv.
- Når kreves imagebygg utover manglende image, og hvordan håndteres endret
  konfigurasjon som krever erstatning av et bevart containerlag?
- Detaljer for config-/navneoppslag, isolerte run-navn, avbrudd og feilbaner
  avklares i research/plan etter at CLI-gjennomgangen er ferdig.
- JSON for strømmede logger og interaktive start/exec/run, inkludert
  kommandoens egne utdata og exitstatus, er ikke detaljavklart.
