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
- `abx proxy apply CONFIG` beholdes for eksplisitt oppdatering av nettverksregler
  og API-nøkler underveis. Proxyen erstattes; agentcontaineren og innloggingen
  beholdes.
- `abx proxy stop NAVN` beholdes som nettverksnødbrems. Proxyen og dens
  tokenmetadata fjernes, slik at utgående tilgang stenges uten å stoppe agenten.
- Nettverksnødbremsen skal ikke vente bak langvarige kontrolloperasjoner som
  imagebygg. Den skal tvinge proxyen ned og bekrefte faktisk fjerning før den
  melder at nettet er stengt. Feil skal rapporteres, ikke presenteres som
  vellykket frakobling. Gjennomføring må fortsatt ivareta ressursidentitet og
  samtidige operasjoner; mekanismen er ikke valgt.
- Miljøet skal også ha en nødbrems: tvungen stopp av agent og proxy uten å
  vente på normal avslutning. `abx stop NAVN --force` er foreslått syntaks;
  konkret flagg og oppryddings-/persistensdetaljer er ikke valgt.
- `abx proxy build` tas ut av bruker-CLI-en. Oppgradering skjer ved
  reinstallasjon; installeren skal bygge nytt proxyimage når proxykoden
  er endret og gjenbruke eksisterende image når den er uendret. Byggingen
  skal kunne reproduseres fra proxykoden og Dockerfilen i repoet.
- `abx login-api-key` fjernes, inkludert kontrolloperasjonen som sender ekte
  nøkkel til Codex. API-nøkler gis gjennom proxyens plassholder-/tokenbytte.
  Kontoinnlogging via nettleser/device-login håndteres av agentverktøyet.
- Registrerte vertskataloger kalles mounts. CLI-gruppen blir `abx mount`:
  add NAVN MAPPE, list, check, repair, revoke og remove. En registrering
  godkjenner én katalog og administrerer dens identitet og filtilgang.
  Katalogen kan inneholde kode, bilder eller andre data.
- `abx mount add NAVN MAPPE` bruker to påkrevde posisjonelle argumenter,
  uten --name eller --path. Utdata viser at registreringen er OK, eller
  konkret hva som er feil. Dette gjelder både menneskemodus og --json;
  JSON følger den felles kontrakten for strukturert suksess eller feil.
- `abx mount list` viser navn, katalogsti og registreringsstatus
  (aktiv/tilbakekalt) i tabell. --json gir tilsvarende strukturerte data.
- `abx mount check NAVN` kontrollerer katalogidentitet og rettigheter for
  operatøren og Agentbox uten å endre noe. --fix reparerer påviste problemer
  gjennom samme reparasjonslogikk som doctor --fix og mount repair.
  Begge utskriftsmoduser viser OK eller konkrete feil, og ved --fix hva som
  er reparert og eventuelt gjenstår.
- Miljøfilens `mounts` bruker `source: NAVN`, `target: /sti/i/container` og
  `mode: ro` eller `rw`. Source refererer til registreringen; target og mode
  velges per miljø. Ett miljø kan bruke flere mounts. Uregistrerte eller
  tilbakekalte kilder avvises uansett eksisterende filrettigheter.
- `abx mount revoke NAVN` trekker tilbake tilgang og beholder registreringen.
  `abx mount remove NAVN` avslutter registreringen etter nødvendig rydding
  av rettigheter og eventuelt eierskap. Ingen av dem sletter katalogen eller
  filene. Refererende miljøfiler beholdes, men kilden kan ikke brukes før
  den igjen er registrert og aktiv.
- `abx doctor` beholdes som samlet diagnose av installasjon/runtime,
  registrerte mounts og deres rettigheter, samt images som mangler bygg.
  Uten --fix undersøker den og rapporterer funn uten å reparere.
- `abx doctor --fix` reparerer påviste problemer gjennom de samme operasjonene
  som blant annet mount repair og image build. Kontroll og reparasjon skal
  gjenbruke eksisterende felles kode, uten parallelle implementasjoner.
  Resultatet viser hva som er reparert og hvilke problemer som gjenstår.
  Gjeldende eierskaps-, bruks- og sikkerhetskontroller gjelder også via --fix.

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
- Mekanisme for å oppdage endret proxykode og ta nytt proxyimage i bruk ved
  oppgradering er ikke valgt. Den må håndtere at gamle proxycontainere finnes.
- Mount remove må bevare grunnlaget for sikker rettighets-/eierskapsrydding
  frem til denne er fullført. Håndtering av miljøer som bruker kilden,
  og konkrete regler for oppryddingen, avklares i research/plan.
- Vurder om separat mount repair skal beholdes som brukerkommando når
  mount check --fix finnes. Intern reparasjonslogikk skal uansett være felles.
- Brukeren vurderer å flytte videre oppfølging til issues. Ingen issues er
  opprettet eller konkret inndeling avklart.
