# Planlagt CLI og livssyklus

Status: vedtatte krav for videre implementasjon.
Dette dokumentet beskriver planlagt oppførsel. Dagens produktkontrakt står i
[produktspesifikasjonen](../../specification.md), og faktisk verifikasjon i
[teststatus](../../test-results.md). Merking som «foreslått» angir detaljer som
fortsatt må fastsettes i research og plan.

## Oppfølging

| Område | Oppgave |
| --- | --- |
| Samle start, exec og run med automatisk livssyklus | [#11](https://github.com/oisteink/agentbox/issues/11) |
| Gjør proxyoppgradering og nødstopp pålitelige | [#12](https://github.com/oisteink/agentbox/issues/12) |
| Utvid imagemaler og bygg ved behov | [#14](https://github.com/oisteink/agentbox/issues/14) |
| Administrer miljøfiler, status og logger | [#15](https://github.com/oisteink/agentbox/issues/15) |
| Samle diagnose og reparasjon i doctor | [#17](https://github.com/oisteink/agentbox/issues/17) |

Felles utskriftskontrakt etableres tidlig. Livssyklus, nødstopp og container-
erstatning samordnes; doctor gjenbruker operasjonene fra mounts og images.

## Kjøring og persistens

- Normal bruk starter nødvendige ressurser automatisk. Brukeren skal ikke
  henvises til en annen kommando når abx har informasjonen som trengs.
- Shell fjernes helt fra CLI-en, uten alias. Start kjører miljøets
  konfigurerte kommando; exec kjører en annen eksplisitt kommando.
- Start, exec, run, validate og proxy apply bruker samme config-oppslag.
  Kortnavn hentes fra ~/.config/agentbox/environments/ med øvrig XDG-støtte;
  eksplisitt filsti bruker den angitte filen. Manglende eller tvetydig filvalg
  gir en konkret feil.
- `abx start CONFIG [--keep-running]` bygger image ved behov, oppretter eller
  starter miljøet og kjører miljøets konfigurerte kommando i terminalen.
- `abx exec CONFIG [--keep-running] -- KOMMANDO` har samme livssyklus, med
  en eksplisitt kommando. Interaktiv terminal velges automatisk når det passer.
  Pipet stdin skal videresendes uten TTY; stdout skal kunne omdirigeres.
- Start/exec registreres som aktive kjøringer knyttet til konkret container.
  Når abx starter containeren for slike kjøringer, stoppes den automatisk
  etter at siste aktive kjøring er ferdig, med mindre --keep-running gjelder.
  Oppstarterens avslutning skal ikke avbryte andre aktive kjøringer.
  En container som allerede står og kjører utenfor denne automatiske
  livssyklusen, stoppes ikke av en kjøring som bare bruker den.
- Oversikten registrerer kjøringene fremfor bare et antall, slik at en
  krasjet klient kan oppdages. Registrering og avgjørelse om vanlig stopp
  samordnes under lås og bindes til containeridentitet; en gammel kjøring
  skal ikke stoppe en erstatningscontainer med samme navn.
- --keep-running lar containeren kjøre etter avsluttet kommando. Den stoppes
  eksplisitt med `abx stop NAVN`. Gjentatt bruk av flagget gir ingen teller
  eller ekstra eierskap.
- Keep-running er ett felles flagg i miljøets gjeldende kjøretilstand. Enhver
  start/exec med --keep-running kan sette det, også mens andre kjøringer er
  aktive. Kjøringer uten flagget nullstiller det ikke. Når siste kjøring
  avsluttes, leses gjeldende flagg før automatisk stopp avgjøres; et tidligere
  snapshot ved oppstart skal ikke overstyre en senere setting av flagget.
  Eksplisitt stop overstyrer flagget og avslutter kjøreperioden.
- `persistent` gjelder containerlaget ved stopp, ikke om miljøet skal stå og
  kjøre. Standard er true: stopp beholder laget, hjemmet og innloggingen.
  Med false fjernes miljøets runtime-ressurser ved stopp.
- Et ikke-persistent miljø kan startes med --keep-running, brukes til flere
  kommandoer/økter i samme container og til slutt fjernes med stop.
- `abx run CONFIG` bruker alltid et nytt, separat midlertidig miljø og fjerner
  bare dette etter bruk. Et eksisterende miljø fra samme konfigurasjon berøres ikke.
- Hver run-instans får et automatisk unikt navn, eksempelvis analyse-run-a1b2.
  Navnet vises ved oppstart og i status mens instansen finnes, og kan brukes
  med logs, stop og nødstopp. Flere run fra samme konfigurasjon kan kjøre
  samtidig. Etter opprydding fjernes instansen fra status; den opprinnelige
  miljøkonfigurasjonen og eventuelt vanlig miljø beholdes.
- `abx remove NAVN` rydder både persistente og ikke-persistente miljøer, også
  kjørende. Allerede fjernede ressurser krever ingen handling.
- Stopp/fjerning sletter ikke miljøkonfigurasjon, filer i mounts eller
  mount-registreringer. Fjerning av containerlaget sletter hjem/innlogging.

## Miljøfiler, status og logger

- `abx status` viser en tabell over alle konfigurerte miljøer, også dem som
  aldri er startet eller har fått containeren fjernet. Oversikten viser
  miljønavn, status (kjører/stoppet/ikke opprettet) og persistens.
- `abx status NAVN` viser detaljer for ett miljø: tilstand, persistens, image,
  mounts/mounts og nettverkstilganger, også uten opprettet container.
- `abx logs NAVN` viser siste utsnitt av agentloggen; `--proxy` velger
  proxyloggen. `-f` / `--follow` følger nye logghendelser fortløpende for
  begge loggtyper. Ctrl-C avslutter loggvisningen uten å stoppe miljøet.
- `abx validate CONFIG` kontrollerer miljøfilen uten oppstart. Menneskemodus
  viser en kort bekreftelse eller konkrete feil; `--json` gir strukturert
  resultat eller feil etter den felles utskriftskontrakten.

## Proxy og nødstopp

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
- `abx stop NAVN --force` er miljøets nødbrems: tvungen stopp av agent og
  proxy uten å vente på normal avslutning. Detaljer for etterfølgende
  opprydding og persistens må fastsettes.
- Nødstopp trumfer aktive kjøringer, eventuell sesjonsregistrering og
  --keep-running. Den skal bryte proxytrafikk og tvinge berørte agentprosesser
  ned uten å vente på normal avslutning, aktive sesjoner eller felles
  operasjonslås. Tyngre opprydding må ikke forsinke selve stansen.
- Nødstopp må være lett å finne og forstå. En global inngang avklares
  uten å innføre en egen agentbox.service bare for tjenestenavnet.
  Global stopp skal avgrenses til Agentbox-miljøer og proxyer, uten å berøre
  andre Docker-instansers ressurser eller slette mountdata.
- Nødstopp skal også hindre at pågående oppstarter eller avslutningslogikk
  gjenoppretter miljø/proxy etter stansen. Ny oppstart skal kreve en eksplisitt
  handling. Nødstopp må fungere uavhengig av vanlig CLI-kø; håndtering av
  en utilgjengelig Docker-daemon og bekreftelse av faktisk stans må avklares.
- `abx proxy rotate-ca NAVN` beholdes. Den stopper miljøet og bytter dets
  CA; neste oppstart bruker den nye CA-en. Agentcontaineren får offentlig
  CA/bundle montert ro, mens privat CA-nøkkel bare er tilgjengelig på
  kontroll-/proxysiden.
- `abx proxy build` tas ut av bruker-CLI-en. Oppgradering skjer ved
  reinstallasjon; installeren skal bygge nytt proxyimage når proxykoden
  er endret og gjenbruke eksisterende image når den er uendret. Byggingen
  skal kunne reproduseres fra proxykoden og Dockerfilen i repoet.
- `abx login-api-key` fjernes, inkludert kontrolloperasjonen som sender ekte
  nøkkel til Codex. API-nøkler gis gjennom proxyens plassholder-/tokenbytte.
  Kontoinnlogging via nettleser/device-login håndteres av agentverktøyet.

## Mounts og volumer

Nye livssykluser bruker den implementerte
[mount-kontrakten](../../usage.md#registrer-delingskilder), inkludert eksplisitt
volumsletting, tilbakekalling og samtykke for fjerning av kildebrukere.

## Diagnose og reparasjon

- `abx doctor` beholdes som samlet diagnose av installasjon/runtime,
  registrerte mounts og deres rettigheter, samt images som mangler bygg.
  Uten --fix undersøker den og rapporterer funn uten å reparere.
- `abx doctor --fix` reparerer påviste problemer gjennom de samme operasjonene
  som mount check --fix og image build. Kontroll og reparasjon skal
  gjenbruke eksisterende felles kode, uten parallelle implementasjoner.
  Resultatet viser hva som er reparert og hvilke problemer som gjenstår.
  Gjeldende eierskaps-, bruks- og sikkerhetskontroller gjelder også via --fix.

## Images og maler

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
- Start og exec bygger automatisk før oppstart hvis imaget mangler eller
  oppskriften er endret siden bygg. Hvis miljøets container allerede kjører,
  brukes den uten ombygging eller erstatning; brukeren varsles om at endret
  oppskrift får virkning etter stopp og ny oppstart. Nytt image tas i bruk
  med ny container; mountene beholdes. Kjørende bruk i andre miljøer gir
  fortsatt byggesperre etter den felles byggeregelen.
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

## Completion og miljøredigering

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
- Ved endret miljøkonfigurasjon tilpasses eller erstattes en stoppet container
  ved neste oppstart. Et kjørende miljø fortsetter med eksisterende oppsett;
  brukeren varsles om at endringer venter til stopp og ny oppstart. Nettverk
  og tokens kan fortsatt aktiveres underveis med proxy apply. Mountdata
  beholdes ved erstatning.
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

Alle nye kommandoer bruker felles menneskeutskrift og
[JSON-kontrakt](../../usage.md#utskrift-og-automatisering). Ingen egen timeout-
opsjon innføres; klienten styrer sin timeout. Destruktive handlinger bruker
felles bekreftelse med `--yes`, også i JSON-modus. `--force` velger tvungen
nødstopp og erstatter ikke samtykke. Logger med follow bruker output-hendelser
og ett sluttresultat når visningen avsluttes.

## Åpent før implementasjon

- Konkrete mekanismer for registrering/opprydding av aktive kjøringer,
  og oppdagelse av krasjede klienter avklares i research/plan. Modellen med
  oversikt over aktive kjøringer og vanlig stopp etter siste kjøring er
  avklart, med et felles keep-running-flagg som kan settes underveis.
- Hvordan oppskriftsendringer oppdages, avklares i research/plan. Automatisk
  bygg ved manglende/endret imageoppskrift og erstatning ved imagebytte er
  avklart. Miljøkonfigurasjonsendringer gjelder ved neste oppstart, med
  eksplisitt proxy apply som mulighet for nettverk/tokens underveis.
- Detaljer for config-/navneoppslag, isolerte run-navn, avbrudd og feilbaner
  avklares i research/plan.
- Mekanisme for å oppdage endret proxykode og ta nytt proxyimage i bruk ved
  oppgradering er ikke valgt. Den må håndtere at gamle proxycontainere finnes.
- Mount remove må bevare grunnlaget for sikker rettighets-/eierskapsrydding
  frem til denne er fullført. Konkrete regler for oppryddingen avklares i
  research/plan; samtykke i JSON-modus håndteres med --yes som avklart over.
