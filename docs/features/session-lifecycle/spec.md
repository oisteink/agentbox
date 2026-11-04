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
- Nettverksregler og tokenreferanser tilhører miljøkonfigurasjonen, med
  network/credentials i miljøfilen. Proxykommandoene styrer miljøets separate
  proxykomponent; det trengs ikke en egen brukerredigert proxykonfigurasjon.
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
- Nødstopp trumfer aktive kjøringer, eventuell sesjonsregistrering og
  --keep-running. Den skal bryte proxytrafikk og tvinge berørte agentprosesser
  ned uten å vente på normal avslutning, aktive sesjoner eller felles
  operasjonslås. Tyngre opprydding må ikke forsinke selve stansen.
- Brukerens eksempel med systemctl stop agentbox beskriver hva en person
  i panikk kan forsøke, ikke et krav om agentbox.service. Ingen slik ny
  tjeneste er ønsket. Nødstopp må være lett å finne og forstå; eventuell
  global inngang avklares uten å innføre en tjeneste bare for dette navnet.
  Global stopp skal avgrenses til Agentbox-miljøer og proxyer, uten å berøre
  andre Docker-instansers ressurser eller slette mountdata.
- Nødstopp skal også hindre at pågående oppstarter eller avslutningslogikk
  gjenoppretter miljø/proxy etter stansen. Ny oppstart skal kreve en eksplisitt
  handling. Nødstopp må fungere uavhengig av vanlig CLI-kø; håndtering av
  en utilgjengelig Docker-daemon og bekreftelse av faktisk stans må avklares.
- `abx proxy build` tas ut av bruker-CLI-en. Oppgradering skjer ved
  reinstallasjon; installeren skal bygge nytt proxyimage når proxykoden
  er endret og gjenbruke eksisterende image når den er uendret. Byggingen
  skal kunne reproduseres fra proxykoden og Dockerfilen i repoet.
- `abx login-api-key` fjernes, inkludert kontrolloperasjonen som sender ekte
  nøkkel til Codex. API-nøkler gis gjennom proxyens plassholder-/tokenbytte.
  Kontoinnlogging via nettleser/device-login håndteres av agentverktøyet.
- Registrerte vertskataloger kalles mounts. CLI-gruppen blir `abx mount`:
  add NAVN MAPPE, list, check, revoke og remove. En registrering
  godkjenner én katalog og administrerer dens identitet og filtilgang.
  Katalogen kan inneholde kode, bilder eller andre data.
- Mount-gruppen skal også håndtere navngitte Docker-volumer, med samme
  registrerte navnerom og source-referanse i miljøfilen. Agentbox håndterer
  lagringen i sin dedikerte Docker-instans. Add NAVN --volume er foreslått
  syntaks for volumopprettelse; vertskataloger bruker add NAVN MAPPE.
  List skal vise mount-type sammen med navn og registreringsstatus.
  Volumer beholdes ved miljøstopp, containerfjerning og imagebytte, inkludert
  avsluttet run; eksplisitt mount remove sletter volumet og volumdataene.
- `abx mount add NAVN MAPPE` bruker to påkrevde posisjonelle argumenter,
  uten --name eller --path. Utdata viser at registreringen er OK, eller
  konkret hva som er feil. Dette gjelder både menneskemodus og --json;
  JSON følger den felles kontrakten for strukturert suksess eller feil.
- `abx mount list` viser navn, katalogsti og registreringsstatus
  (aktiv/tilbakekalt) i tabell. --json gir tilsvarende strukturerte data.
- `abx mount check NAVN` kontrollerer katalogidentitet og rettigheter for
  operatøren og Agentbox uten å endre noe. --fix reparerer påviste problemer
  gjennom samme interne reparasjonslogikk som doctor --fix.
  Begge utskriftsmoduser viser OK eller konkrete feil, og ved --fix hva som
  er reparert og eventuelt gjenstår.
- Miljøfilens `mounts` bruker `source: NAVN`, `target: /sti/i/container` og
  `mode: ro` eller `rw`. Source refererer til registreringen; target og mode
  velges per miljø. Ett miljø kan bruke flere mounts. Uregistrerte eller
  tilbakekalte kilder avvises uansett eksisterende filrettigheter.
- Mount repair tilbys ikke som egen brukerkommando. Reparasjonen er felles
  intern funksjonalitet bak mount check --fix og doctor --fix.
- `abx mount revoke NAVN` trekker tilbake tilgang og beholder registreringen.
  Hvis kjørende miljøer bruker kilden, advares brukeren med navnene på disse
  miljøene og at åpne filhåndtak kan beholde tilgang. Tilbakekallingen gjennomføres
  uten automatisk stopp; nye monteringer avvises. Dette lover ikke umiddelbar
  tilbakekalling av all eksisterende tilgang.
  `abx mount remove NAVN` avslutter registreringen etter nødvendig rydding
  av rettigheter og eventuelt eierskap for vertskataloger. Katalogen og filene
  beholdes. For Docker-volumer sletter remove både volumet og innholdet.
  Revoke beholder innhold for begge typer. Refererende miljøfiler beholdes,
  men kilden kan ikke brukes før den igjen er registrert og aktiv.
- Hvis kjørende miljøer bruker en kilde som skal fjernes med mount remove,
  vises hvilke miljøer som berøres og brukeren tilbys å stoppe dem og fullføre
  fjerningen. Ved avslag beholdes registreringen. Opprydding må lykkes før
  registreringen fjernes; feil beholder grunnlaget for nytt forsøk.
- `abx doctor` beholdes som samlet diagnose av installasjon/runtime,
  registrerte mounts og deres rettigheter, samt images som mangler bygg.
  Uten --fix undersøker den og rapporterer funn uten å reparere.
- `abx doctor --fix` reparerer påviste problemer gjennom de samme operasjonene
  som mount check --fix og image build. Kontroll og reparasjon skal
  gjenbruke eksisterende felles kode, uten parallelle implementasjoner.
  Resultatet viser hva som er reparert og hvilke problemer som gjenstår.
  Gjeldende eierskaps-, bruks- og sikkerhetskontroller gjelder også via --fix.
- `abx image new NAVN --template MAL` kan bruke både medfølgende maler
  (base, codex, opencode, claude-code) og lokale imageoppskrifter som mal.
  Oppskriften kopieres med Dockerfile, .dockerignore og hjelpeskript;
  den trenger ikke være bygget. Kopien er selvstendig og følger ikke senere
  endringer i malen. Eksisterende målkatalog overskrives ikke.
- Egne oppskrifter/maler ligger under ~/.config/agentbox/images/ (med samme
  XDG-støtte som øvrig brukerkonfigurasjon). Uten --template brukes lokal
  oppskrift med navnet default hvis den finnes, ellers medfølgende base.
  Egen standard redigeres med `abx image edit default`.
- Autocomplete for --template foreslår både lokale oppskrifter og medfølgende
  maler. De medfølgende malene beholdes og lagres som installasjonseid innhold,
  utenfor brukerstyrt .config. /usr/share er nevnt som mulig plassering;
  konkret installasjons-/pakkesti er ikke fastsatt.
- Installasjon/reinstallasjon gjenoppretter installasjonens medfølgende malfiler.
  Lokale maler overstyrer medfølgende maler ved samme navn; lokal default er
  tilsvarende brukerens valg av standard. Lokale oppskrifter beholdes ved
  installasjon. Ingen særskilt mekanisme for å omgå lokale overrides er påkrevd.
- `abx image edit NAVN` rapporterer etter editoravslutning om den lokale
  oppskriften ble endret eller om det er ingen endringer. Det omfatter også
  .dockerignore og hjelpeskript i oppskriftskatalogen. --json gir tilsvarende
  strukturert endringsstatus. Redigering utløser ikke automatisk bygging.
- `abx image build NAVN` tillates når alle containere som bruker imaget er
  stoppet. Kjørende bruk sperrer bygging; stoppede containere skal ikke måtte
  fjernes først. Byggingen oppdaterer image/tag uten å endre eksisterende
  containerlag.
- Oversiktskommandoene bruker navnet list: `abx image list` og `abx mount list`.
  Image ls erstattes av image list; det trengs ikke et ls-alias.
  Imageoversikten viser lokale oppskrifter og byggestatus, også ubygde.
  Full liste over miljøer som bruker imaget legges i detaljvisningen,
  slik at oversikten ikke får en ubegrenset «brukes av»-kolonne.
- `abx image inspect NAVN` viser oppskriftskatalog, byggestatus, image-ID og
  hvilke miljøer som bruker imaget. Standardutskriften er lesbar for mennesker;
  --json gir tilsvarende strukturerte detaljer.
- `abx image remove NAVN` erstatter image rm. Den fjerner det bygde imaget,
  men beholder den lokale Dockerfilen og resten av oppskriften for senere bygg.
  Fjerning avvises når containere bruker imaget, også stoppede containere.
  Dette er forskjellig fra bygging, som tillates når alle brukere er stoppet.
- `abx completion bash` beholdes for aktivering i et eksisterende skall.
  Installeren setter opp completion for nye Bash-skall med bash-completion.
  Forslag omfatter kommandoer, flagg, miljøer, mounts, images, imagemaler og
  relevante filstier. Andre skall er ikke avtalt.
- `abx env new NAVN` oppretter en ny, redigerbar miljøfil under
  ~/.config/agentbox/environments/ (med samme XDG-støtte som øvrig konfigurasjon).
  Eksisterende fil gir feil og overskrives ikke. Resultatet rapporteres
  som OK eller konkret feil etter den felles utskriftskontrakten.
- `abx env edit NAVN` åpner en eksisterende miljøfil med samme editorvalg som
  image edit. Manglende miljøfil gir feil. Etter editoravslutning rapporteres
  om filen ble endret, etter den felles utskriftskontrakten.
- Miljøinnstillinger konfigureres kun i miljøfilen: image, mounts, nettverk,
  tokenreferanser/miljøvariabeloppsett, command, resources og persistent.
  Env edit er en snarvei til filen; CLI-en tilbyr ikke flagg for å koble til
  eller overstyre mounts, nettverk eller miljøvariabler ved kjøring.
  --keep-running og eksplisitt kommando til exec er kjørevalg. Ekte tokenverdier
  leses fra operatørens miljø; miljøfilen inneholder referanser, ikke nøkler.
- `abx env delete NAVN` rydder eventuelle opprettede miljøressurser før
  miljøfilen slettes. Mount-registreringer, volumdata og imageoppskrifter
  beholdes. Kjørende miljø vises, og brukeren spørres om å stoppe og fjerne
  det før sletting. Ved avslag beholdes miljøet og miljøfilen.
- Data som skal overleve et nytt image må ligge i eksplisitte mounts.
  Det gjelder også verktøyprofil, innlogging eller hjemmekatalog når brukeren
  ønsker å bevare dette. Ved neste start med nytt image kan abx erstatte den
  stoppede containeren og beholde mountene. Persistent true bevarer laget
  mellom vanlige stopp/start, men gir ikke bevaring gjennom imagebytte.
  Profiler kan monteres på den stien verktøyet bruker; containerens faktiske
  HOME og profilplassering må beskrives tydelig i oppsettet.

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
  konfigurasjon som krever erstatning av et bevart containerlag? Imagebytte
  er avklart: containerlaget er disponibelt, varige data skal ligge i mounts.
- Detaljer for config-/navneoppslag, isolerte run-navn, avbrudd og feilbaner
  avklares i research/plan etter at CLI-gjennomgangen er ferdig.
- JSON for strømmede logger og interaktive start/exec/run, inkludert
  kommandoens egne utdata og exitstatus, er ikke detaljavklart.
- Mekanisme for å oppdage endret proxykode og ta nytt proxyimage i bruk ved
  oppgradering er ikke valgt. Den må håndtere at gamle proxycontainere finnes.
- Mount remove må bevare grunnlaget for sikker rettighets-/eierskapsrydding
  frem til denne er fullført. Konkrete regler for oppryddingen og samtykke
  til stopp i JSON-/ikke-interaktiv modus avklares i research/plan.
- Brukeren vurderer å flytte videre oppfølging til issues. Ingen issues er
  opprettet eller konkret inndeling avklart.
