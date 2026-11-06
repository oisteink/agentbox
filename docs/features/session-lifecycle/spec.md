# Planlagt CLI og livssyklus

Status: vedtatte krav for videre implementasjon.
Dette dokumentet beskriver planlagt oppførsel. Dagens produktkontrakt står i
[produktspesifikasjonen](../../specification.md), og faktisk verifikasjon i
[teststatus](../../test-results.md). Merking som «foreslått» angir detaljer som
fortsatt må fastsettes i research og plan.

## Oppfølging

| Område | Oppgave |
| --- | --- |
| Gjør proxyoppgradering og nødstopp pålitelige | [#12](https://github.com/oisteink/agentbox/issues/12) |
| Administrer miljøfiler, status og logger | [#15](https://github.com/oisteink/agentbox/issues/15) |
| Samle diagnose og reparasjon i doctor | [#17](https://github.com/oisteink/agentbox/issues/17) |

Felles utskriftskontrakt etableres tidlig. Livssyklus, nødstopp og container-
erstatning samordnes; doctor gjenbruker operasjonene fra mounts og images.

## Kjøring og persistens

Videre arbeid bruker den implementerte [livssyklusen](../../usage.md#avbrutte-kjøringer)
med aktive kjøringer, delt keep-running og separate run-instans­er. Nødstopp
må overstyre registreringer og håndtere journalførte launch-intents uten
å gjenopprette en stoppet generasjon.

## Miljøfiler, status og logger

- `abx status` viser en tabell over alle konfigurerte miljøer, også dem som
  aldri er startet eller har fått containeren fjernet. Oversikten viser
  miljønavn, status (kjører/stoppet/ikke opprettet) og persistens.
- `abx status NAVN` viser detaljer for ett miljø: tilstand, persistens, image,
  mounts og nettverkstilganger, også uten opprettet container.
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

Livssyklusarbeidet bruker [image-klargjøringen](../../usage.md#lokale-maler-redigering-og-bygg)
med lokale maler, inputdigest, bygg ved behov og erstatning av stoppede
containere. Pending endrer ikke kjørende agent/proxy. Exec er bundet til valgt
agent-ID; øvrige kontrolloperasjoner skal bevare denne grensen.

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

- Mekanisme for å oppdage endret proxykode og ta nytt proxyimage i bruk ved
  oppgradering er ikke valgt. Den må håndtere at gamle proxycontainere finnes.
