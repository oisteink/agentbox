# Spesifikasjon for Agentbox

Agentbox kjører kodeagenter mot eksplisitt valgte vertskataloger på én
Linux-vert. Én utvikler administrerer oppsettet og kan bruke flere miljøer
samtidig, med ulike images, mounts og nettverkspolicyer.

Dette er produktkontrakten for Agentbox. [Bruksveiledningen](usage.md)
beskriver kommandoene, [arkitekturen](architecture.md) forklarer oppbygningen,
og [teststatus](test-results.md) avgrenser hva som er verifisert.

Planlagte endringer i CLI og livssyklus står i [egen kravspesifikasjon](features/session-lifecycle/spec.md)
og er ikke del av kontrakten nedenfor.

Kommandonavnet er `abx`, både ved pakkeinstallasjon og vertsinstallasjon.
Hjelp, feilmeldinger og Bash-completion bruker dette navnet.

## Begreper og tillit

| Begrep | Betydning |
| --- | --- |
| Utvikler | Personlig Linux-bruker som registrerer mounts og styrer miljøer |
| Tjenestebruker | `agentbox`, som kjører rootless Docker uten vertens root-rettigheter |
| Mount | Registrert vertsmappe eller navngitt lokalt Docker-volum |
| Miljø | Navngitt agentcontainer, proxy og egne nettverk med felles livssyklus |
| Miljøfil | YAML som velger image, kommando, arbeidskatalog, mounts og destinasjoner |
| Kontrollside | Installerte vertsprogrammer, privat tilstand og administrasjon av Docker |

Agenten og kode den kjører behandles som upålitelige. Utvikleren,
kontrollkoden, Docker, proxyen, valgte images og vertsadministrasjon er betrodd.
Miljøfiler oppbevares utenfor mapper agenten kan redigere. Kontrollkode og privat
kontrolltilstand monteres ikke inn i agentcontaineren. Bare miljøets offentlige
CA-katalog deles skrivebeskyttet inn fra kontrollsiden.

Rootless-containere deler vertens kjerne. Utbrudd med tjenestebrukerens
rettigheter kan gi tilgang til alle registrerte mounts og andre filer som
er tilgjengelige for lokale brukere. Tillatte destinasjoner kan brukes til å
sende data ut; domenepolicyen gir ingen innholdsfiltrering.

## Vertsplattform og kontroll

- Linux med systemd, cgroup v2, user namespaces, POSIX ACL og Python 3.12 eller nyere.
- Debian er målplattformen; Ubuntu brukes også til labprøver. Konkret minste
  Debian-versjon er ikke fastsatt utover forutsetningene over.
- Docker Engine og CLI 28 eller nyere. Den testede versjonen er 29.9.3;
  øvrige versjoner har ikke samme prøvegrunnlag.
- Egen Linux-bruker `agentbox`, privat hjem `/var/lib/agentbox` med modus 0700
  og egen Docker-konfigurasjon. Runtime-socket ligger under `/run/user/<uid>`.
- Administrator installerer kontrollkode under `/opt/agentbox` og innstillinger
  i `/etc/agentbox/settings.json`. Den private ACL-journalen ligger separat i
  `/var/lib/agentbox-operator` og eies av utvikleren.
- Installeren bruker `SUDO_USER` som standard utvikler. `--operator BRUKER`
  velger en annen bruker og kreves ved direkte root-kjøring. Root og
  tjenestebrukeren kan ikke være utvikler.
- Daglige Docker-operasjoner går via en fast sudo-hjelper som `agentbox`, med
  strukturert JSON på stdin og renset prosessmiljø. Fast socket, rootless-modus,
  daemon-ID, datasti, Docker-versjon og rapportert cgroup-støtte kontrolleres.
- Andre Docker-instansers konfigurasjon og context endres ikke. Docker-socketen
  eksponeres ikke over ubeskyttet TCP eller i agentcontainerne.

`doctor` kontrollerer daemonforutsetningene. Installeren kontrollerer
UID/GID-forutsetninger, `mount check` kontrollerer mount-tilgang, og labprøver
verifiserer faktisk håndheving av ressursgrenser.

## Mount-registrering, lagring og ACL

Et mount er en registrert kilde med navn, type og status. `mount add NAVN MAPPE`
registrerer en katalog; `mount add NAVN --volume` oppretter et navngitt lokalt
Docker-volum. Samme navn og kilde kan gjenbrukes og reaktiveres etter revoke.
Annen type, sti eller katalogidentitet ved samme navn gir konflikt.
Miljøfiler bruker `mounts[].source`. Uregistrerte og tilbakekalte kilder nektes
uansett øvrige filrettigheter. Privat tilstand bruker skjema 2.

Kataloger registreres uten flytting. Roten må eies av operatøren. Lagret enhet,
inode og eier kontrolleres ved bruk. ACL-er gir begge brukere tilgang; vanlige
filer får ikke kjørbarhet. Foreldrekataloger får traversering uten listetilgang.
Standard-ACL-er støtter nye filer. Andre brukeres effektive rettigheter bevares.
Overlappende røtter, hardlenkede ordinære filer, spesialfiler og ukjente eiere
avvises. Symlinker følges ikke ved ACL-endring; nestede mounts utelates før åpning.

Volumer har local-driver uten options og etiketter for installasjon, navn og
registreringsidentitet. Fremmede/endrede eller manglende volumer avvises ved
bruk. De gjenskapes ikke av start eller diagnose. `volume-nocopy` hindrer at
imageinnhold fylles inn automatisk. Named volumes og katalogdata overlever
miljøstopp, containerfjerning, run og imagebytte. Faktisk HOME `/home/agent`
og profilstier kan monteres eksplisitt; operatørens hjem deles ikke automatisk.

`mount check NAVN [--fix]` undersøker katalogidentitet og begge brukeres
tilgang, eller volumets driver og eiermerking. Den viser OK eller konkrete
feil. Fix gjenbruker tildeling/tilbakekalling, åpner aldri revoked og avviser
pågående removing. Katalogtildeling krever stoppede brukere. Helt utilgjengelige
trær og ukjente eiere kan kreve manuell retting fra fileieren.

Revoke lagrer nektet registrering og beholder data. Katalogroten får en deny-
ACL; volumet har en registreringssperre. Kjører miljøer med kilden, navngis de
med advarsel om fortsatt tilgang gjennom monteringer og åpne filhåndtak.
De stoppes ikke automatisk. Nye monteringer nektes.

Remove innhenter samtykke før kjørende katalogbrukere stoppes. Ikke-persistente
brukere mister containerlaget. Volumbrukere fjernes helt, også stoppede
containere, før volumet og alt innhold slettes. Samtykket bindes til kilde og
berørte miljøressurser; fremmede containerreferanser avvises. JSON bruker
confirmation_required uten spørsmål; --yes gir samtykke.

Katalog-remove beholder filer/eierskap og operatør-ACL på agentbox-eide filer.
Service-ACL-er og ubrukte traverseringsgrants ryddes med to eieravgrensede pass
mot komplett, identitetskontrollert inventar. Resultatet oppgir at service-
eiertilgang kan bestå, og at avregistrerte filer er utenfor senere uninstall-
opprydding. Normalhjelperen har ikke root/chown. Feil beholder removing og
grunnlaget for retry; journalen lagres før registeret glemmes. Manuelle ACL-
endringer bevares ved at bare serviceoppføringer fjernes der snapshot avviker.
Miljøfiler beholdes og kan brukes når kilden igjen er aktiv.

## Miljøkonfigurasjon

`abx start FIL.yaml` leser miljønavnet fra `name` i miljøfilen.
Kommandoer som `shell` og `stop` bruker miljønavnet; exec bruker miljøfil eller kortnavn.
`start`, `run`, `exec`, `validate` og `proxy apply` støtter også kortnavn uten filending fra
`~/.config/agentbox/environments/` (eller `$XDG_CONFIG_HOME/agentbox/environments/`).
`.yaml` og `.yml` støttes. Hvis begge matcher, kreves eksplisitt filvalg.
Lokale filer uten filending overstyrer ikke kortnavn; bruk eksplisitt sti for slike filer.

YAML-filen avviser ukjente felter og dupliserte nøkler. Verdier for hemmeligheter,
vilkårlige Docker-flagg og automatisk hjemmedeling inngår ikke i skjemaet.
Mount-, miljø- og imagenavn starter med en liten bokstav og bruker deretter
små bokstaver, tall og bindestrek, maksimalt 48 tegn.

| Felt | Kontrakt og standardverdi |
| --- | --- |
| `name` | Påkrevd unikt miljønavn; leses fra YAML-filen ved start |
| `image` | Påkrevd lokalt oppskriftsnavn, for eksempel `codex` eller `js` |
| `mounts` | 1 til 32 registrerte mounts, hvert med `source`, absolutt `target` og `mode` (`rw` som standard eller `ro`) |
| `workdir` | Sti inne i valgt mount; standard er første mountmål. Undermapper i katalogmounts må finnes |
| `persistent` | Boolsk, standard `true`. Med `false` fjerner `shell` miljøet etter kommandoen; `stop` fjerner det også |
| `command` | 1 til 128 ikke-tomme argumenter; standard `["bash"]`. Kjøres av `shell` og `run`, uten shelltolking |
| `network.allow` | Liste over eksakte `host`/`port`-par, maksimalt 128. Tom som standard |
| `credentials` | Maksimalt 32 regler med `host`, `port: 443`, `header` og `env`; tom som standard. Se [tokenreglene](#api-tokens-på-proxysiden) |
| `resources.cpus` | 0,1 til 128; standard 2 CPU |
| `resources.memory` | Positiv størrelse med `m` eller `g`; standard `4g` |
| `resources.pids` | 16 til 65536; standard 512 |

Mountmål som overlapper eller treffer reserverte systemstier avvises.
Kildemapper må være registrerte og eksistere; manglende mapper opprettes ikke.
Mountene har privat propagasjon og inkluderer ikke underliggende mounts.
Kataloginnhold som `.env` blir tilgjengelig hvis det ligger i valgt mount.

Images må støtte amd64 eller arm64, UID 0, `/bin/sh` og `sleep infinity`.
Deklarerte `VOLUME`-mounts avvises. Det valgte imagets entrypoint erstattes
av miljøets oppholdsprosess; valgt arbeidskommando kjøres separat.
Imagevalg endrer ikke ACL-, nettverks- eller isoleringsmekanismene.

### Lokale imageoppskrifter

Alle agentimages har lokale Dockerfiles under XDG/~/.config/agentbox/images.
`image new NAVN` kopierer lokal default hvis den finnes, ellers medfølgende
base. `--template MAL` velger en lokal oppskrift eller medfølgende base,
codex, opencode eller claude-code; lokal mal vinner ved samme navn. Hele
konteksten kopieres, med skjulte filer, underkataloger, modus og lenker som
lenker. Kopien er selvstendig og eksisterende mål overskrives ikke.
Medfølgende maler ligger i pakkens templates-katalog; vertsinstallasjonen
bruker /opt/agentbox/lib/agentbox/templates og reinstallasjon gjenoppretter den.
Brukerens oppskrifter erstattes ikke. Wheel inkluderer malenes .dockerignore.

`image list` viser lokale/ubygde oppskrifter med built/stale/unbuilt-status.
Ingen lang brukerliste vises. `image inspect NAVN` viser path, tag, ID, input-
digest og berørte miljøer/containere. `image remove NAVN` fjerner bygget tag og
beholder oppskriften; eksisterende brukere, også stoppede, sperrer fjerning.

`image edit NAVN` bruker VISUAL, EDITOR eller editor, med siterte argumenter
uten shelltolking. Editor arver vanlig terminal/miljø og bruker oppskriftens
katalog. Resultatet viser changed/unchanged for hele konteksten og editorens
exitstatus, også ved ikke-null status. Ingen bygg skjer direkte ved edit.

`image build NAVN` bygger i dedikert rootless Docker. Kjørende brukere sperrer
bygg; stoppede brukere gjør det ikke. Brukssjekken følger konkrete container-
referanser, også etter tagflytting, uten å klassifisere avledede images ut fra
arvede image-labels. Kontrolloperasjonens lås dekker sjekk og bygg.

Inputdigest beregnes fra mottatt tars sti/type/modus/lenkemål og filbytes, uten
mtime/eier/padding. Samme funksjon brukes lokalt. Stamp lagres som imagelabel;
ingen egen byggdatabase brukes. Hele overførte konteksten teller konservativt,
også filer Docker ignorerer. Docker selv behandler .dockerignore fra katalogen.
Lenker følges ikke ved pakking; datafilter avviser utpakking utenfor konteksten
og spesialfiler. Arkiv og privat midlertidig katalog slettes etter bygg.

Start, run og exec bygger ved manglende/endret input. Kontrollstart verifiserer
riktig digest under lås før stoppet/nytt miljø brukes. Ved image-race klargjøres
samme handling igjen, maksimalt tre forsøk. Kjørende miljø brukes uendret med
beskjed om pending; proxy/policy beholdes også når proxyen er stoppet/mangler.
Stoppet miljø erstattes ved endret image-ID, konfigurasjon, klientvariablenes
tom/ikke-tom-tilstand eller vertsadresser, med bevarte mounts. Profil, mounts,
DNS og tokenverdier valideres før det gamle containerlaget slettes.
Registryimages kan brukes i Dockerfilens FROM; baseoppdateringer utløser ikke
bygg uten endret lokal input eller eksplisitt image build.

Installeren bygger den interne proxykomponenten hvis imaget mangler, med
samme daemonverifikasjon og operasjonslås som kontrollverktøyet. Byggingen
kjører som agentbox med rent miljø; feil gir mislykket installasjon.
Eksisterende image beholdes, også når containere bruker det. `proxy build`
bygger komponenten eksplisitt fra installert kilde og beholder brukssperren.
Proxyen inngår ikke i image list.

Agentens UID 0 mappes til tjenestebrukeren på verten. Den kjører med droppede
capabilities, `no-new-privileges`, ressursgrenser og en revisjonslåst Moby-
seccomp-profil med strengere sperrer mot Unix-sockets og alternative socket-
syscalls. Privilegert modus, vertsnettverk, vertens PID-namespace og ekstra
enheter tilbys ikke. Verktøy som trenger filsystem- eller abstrakte Unix-
sockets støttes ikke.

## Nettverk og proxy

Hvert miljø har et lukket `isolated` bridge-nettverk, et eksternt nettverk og
en egen Go-proxycontainer. Agenten kobles bare til det lukkede nettverket.
Proxyen har ett grensesnitt på hvert nett, lytter bare internt og videresender
ikke IP-trafikk. Ingen porter publiseres til vert eller LAN.

- Utgående agenttrafikk avvises som standard. Bare eksakte domene/port-par
  tillates, uten implisitte underdomener.
- HTTP på 80 og HTTPS via CONNECT på 443 støttes. Vanlig tillatt HTTPS er
  en tunnel. Eksplisitte credentials-regler aktiverer TLS-avlytting og
  headerinnsetting for valgt destinasjon, uten generelle sti-/body-regler.
- IP-litteraler og navn med ikke-offentlige adresser eller vertens egne adresser
  avvises. Kontrollsiden validerer alle DNS-svar og fastlåser én offentlig
  IPv4-adresse per navn. Proxyen har ingen ekstern DNS-fallback.
- Agentens IPv6 er deaktivert. Direkte ekstern TCP, UDP og QUIC samt tilgang
  til vert, LAN og andre miljøer blokkeres uavhengig av proxyvariabler.
  Agenten har ingen ubegrenset ekstern DNS-kanal.
- En adressevakt stopper miljøer ved endrede vertsadresser. Vakten er asynkron,
  deler lås med kontrolloperasjoner og gir ingen atomisk sperring i selve
  endringsøyeblikket. Nettverksadministrasjon på verten er betrodd.
- Proxyen får bare konfigurasjon og fastlåste adresser montert skrivebeskyttet.
  Ingen vertskataloger eller Docker-socket deles inn i proxyen. API-tokens
  tilføres bare proxyens miljø ved start/apply; konfigurasjon har referanser.
- Bortfall av proxyen åpner ingen alternativ utgående vei.

Adresseområdet velges i administratorinnstillingen `network_pool`.
Det må ha minst to ledige `/28`-subnett; vertsruter og eksisterende nettverk
på Agentbox-daemonen utelukkes. Standardområdet er `172.28.0.0/16`.
Proxyens faste ressursgrenser er 0,5 CPU, 256 MiB og 128 prosesser.

Imagebygging og henting av baseimages skjer på den betrodde kontrollsiden utenfor
agentens nettverkspolicy. Agenten har ingen kontrollkanal for å bestille slike
operasjoner. Innloggingsdomener, API-er, MCP-tjenester og pakkeregistre må
velges eksplisitt for trafikk fra miljøet.

## Livssyklus, lagring og diagnostikk

| Operasjon | Oppførsel |
| --- | --- |
| `start FIL.yaml` | Leser miljønavnet fra filen, validerer miljø og mounts, oppretter nettverk og proxy før agent; uendret kjørende miljø gjenbrukes |
| `run FIL.yaml` | Kjører command én gang i terminalen i et nytt miljø; fjerner containere, nettverk og containerlag ved avslutning eller Ctrl-C; filer i katalogmounts beholdes |
| `shell` | Kjører miljøets konfigurerte kommando; med `persistent: false` fjernes miljøet etterpå, også ved feil eller Ctrl-C |
| `exec CONFIG -- KOMMANDO` | Bygger/starter ved behov og kjører argumentlisten i valgt konkret agentcontainer; beholder kjørende proxytilstand |
| `stop` | Med `persistent: true` stoppes agent og proxy og containerlaget beholdes; med `false` fjernes miljøet. Mount-registreringer beholdes |
| `remove` | Fjerner miljøets containere, nettverk og logger; filer i katalogmounts og ACL-er beholdes |
| `status` | Viser registrert miljøoppsett og observert containertilstand |
| `logs` | Viser et begrenset utsnitt av agentutdata eller proxylogg med `--proxy` |

Et stoppet miljø gjenopptas med uendret konfigurasjon og vertsadresser.

Med `persistent: true` beholdes containerens `/home/agent`, innlogging og
installerte filer, også ved manuell gjenopptak etter daemonrestart. Automatisk oppstart av miljøer
etter vertsreboot finnes ikke.

Endret image, profil, klientvariabeltilstand eller vertsadresse gir automatisk
erstatning ved oppstart av stoppet miljø. Containerlaget slettes; data i
katalog-/volummounts består. Nettverk/tokenregler endres med proxy apply uten å slette
agentlaget. Gjenopptak av stoppet miljø og apply validerer DNS på nytt.

`persistent: false` gir ingen bevart container mellom shell-økter. Start
klargjør i bakgrunnen og varsler om miljøets levetid. Shell varsler før
kommandoen kjøres og reserverer én økt under lås. Flere shell-forsøk avvises uten opprydding av
den aktive økten. Reservasjonen beholdes ved start/proxy apply; etter et
hardt prosessavbrudd kreves eksplisitt remove. Exec er en ekstra kommando
og utløser ikke opprydding, men prosessen fjernes sammen med miljøet.

`run` er alltid midlertidig og avviser eksisterende miljønavn. Kommandoens
exitkode returneres etter vellykket opprydding; oppryddingsfeil gir feilstatus. Opprettelse og fjerning
bruker vanlig daemonverifikasjon og lås, mens kommandoen kjøres uten global
lås. Opprydding etter run og ikke-persistent shell sjekker valgt agent-ID
mot ny tilstand, slik at et gjenskapt miljø med samme navn ikke fjernes. SIGINT utsettes under kritiske mutasjoner.
SIGKILL og vertskrasj kan etterlate ressurser som må fjernes eksplisitt.

Terminalsesjoner i vedvarende miljøer har separat levetid fra miljøet.
`start` starter oppholdsprosessen, ikke `command`. `run`, `shell` og `exec`
bruker terminal bare når både CLI-ens stdin og stdout er terminaler og JSON
ikke er valgt. Uten terminal videresendes stdin, og stdout/stderr holdes atskilt.
Standardutskrift er for mennesker. `--json` gir JSON Lines med output-hendelser
og ett terminalt resultat med `ok`, `data` eller `error.code/message`, samt
`exit_code` for prosesser. Håndterte feil, kommandofeil og håndtert Ctrl-C gir
CLI-exitkode 0 i JSON-modus. Manglende terminalresultat er ikke suksess.
`--yes` gir samtykke; maskinmodus spør aldri interaktivt. Detaljert kontrakt
står i [bruksveiledningen](usage.md#utskrift-og-automatisering).
Terminalstørrelse og størrelsesendringer videresendes. Kontrolloperasjoner låses,
tilstand skrives atomisk, og opprydding avgrenses med ressurs-ID-er og
installasjons-/miljøetiketter. Global Docker-prune brukes ikke. Testavgrensninger
for krasj og samtidighet står i teststatus.

Agentnøkler gis eksplisitt per miljø. `login-api-key` krever en privat fil eid
av utvikleren og sender nøkkelen via stdin. Kontrollverktøyet logger ikke
nøkkelverdier eller forespørsler. Agentens egne utdata kan inneholde hemmeligheter;
disse loggene er private og roterte uten generell filtrering. Proxyloggen
inneholder destinasjon og resultat uten URL-sti eller query.

CLI-en tilbyr Bash-completion for kommandoer, flagg, registrerte mounts,
eksisterende miljøer og relevante filstier. Dynamiske navneoppslag ber ikke om
sudo-passord og har en tidsgrense på to sekunder.

## Verifikasjonskriterier

Integrasjonsprøver bruker midlertidige mapper og kontrollerte
nettverksdestinasjoner. Forventet
blokkering bekreftes mot en fungerende kontrolltjeneste. Observerte resultater,
manuell utprøving og utestede kombinasjoner står i [teststatus](test-results.md).
Testenes ansvar, kravdekning og regler ved endringer står i
[teststrategien](testing.md). Bevaring skal undersøkes utenfor mountene;
negative prøver skal bekrefte riktig avvisning og relevante konsekvenser.

| ID | Verifikasjon |
| --- | --- |
| A1 | Miljøet bruker riktig daemon; feil eller rootful daemon avvises |
| A2 | To miljøer kjører samtidig; stopp og opprydding av ett lar det andre fortsette |
| A3 | Bare valgte vertsmapper er synlige; en kontrollmappe ved siden av mountet er utilgjengelig |
| A4 | Begge brukerne kan opprette, redigere, erstatte og slette testfiler; kjørbare filer beholder kjørbarhet |
| A5 | Skrivebeskyttede mounts avviser skriving; kodeendringer overlever fjerning av miljøet |
| A6 | Tillatte HTTP- og HTTPS-destinasjoner fungerer gjennom proxy; andre domener og porter avvises |
| A7 | Direkte IPv4/IPv6 og UDP blokkeres uten proxyvariabler; vert, LAN og andre miljøer er utilgjengelige |
| A8 | DNS gir ingen ubegrenset ekstern kanal; tillatt navn som peker til intern adresse avvises |
| A9 | Stoppet proxy og ugyldig policy gir ingen alternativ utgående tilgang |
| A10 | Agenten kan ikke endre policy, nå Docker-socketen eller opprette egne mounts/nettverk |
| A11 | To images fungerer med samme kontroll-, mount- og nettverksmekanisme |
| A12 | CPU-, minne- og prosessgrenser verifiseres; manglende støtte gir feil |
| A13 | Tilbakekalling av mount-tilgang bevarer uvedkommende ACL-er og tilgang til andre registrerte mounts |

## Avinstallasjon

`sudo scripts/uninstall.sh` er en administratoroperasjon som stopper alle Agentbox-
miljøer, overfører tjenestebrukerens filer i katalogmounts til utviklerens UID/GID og
fjerner installasjon, tjenester, hjem, images, privat tilstand og tjenestebruker.
`--dry-run` viser omfanget uten å endre filer eller tjenester. Løpende miljøer
gir en advarsel og stoppes; brukeren trenger ikke avvikle dem manuelt først.

Tilbakekalte katalogmounts i registeret inngår i filryddingen. Volumdata slettes
med den dedikerte Docker-lagringen. Avregistrerte kataloger ryddes ikke. Røttene valideres mot
lagret identitet. Symlinker følges ikke, men selve linkens eierskap overføres.
Nestede mounts hoppes over, og berørte hardlenker avvises for å unngå endring
av filer utenfor mountet. Kataloginnhold og brukerens miljøfiler beholdes.

Kun tjenestebrukerens ACL-oppføringer fjernes fra innholdet; øvrige oppføringer
og masker beholdes. Journalførte foreldre gjenopprettes når uendret, ellers
fjernes bare tjenestebrukerens oppføring. Katalogrydding må lykkes før
konto og installasjonsdata slettes. Operasjonen tar journal- og kontrollås i
samme rekkefølge som mount-operasjonene og stenger den vanlige sudo-hjelperen
før prosesser stoppes. Den gir ikke nye root-rettigheter gjennom den vanlige
kontrollhjelperen.

## Utenfor denne leveransen

- Linked worktrees og deres delte Git-metadata.
- Egen vertsbruker eller VM per miljø og sterkere runtime som gVisor.
- Generelle URL-/body-regler, vilkårlig TCP-proxy og utgående SSH.
- GUI, fjernkjøring, flerbrukerplattform og automatisk håndtering av agentkontoer.

Videre vurdering omfatter sammenligning med OpenShell og Docker Sandboxes.
Arbeidet skal undersøke faktiske isoleringsgrenser, nettverkspolicy, mounts,
filrettigheter, samtidige miljøer, imagevalg, plattformkrav og vedlikehold.

## API-tokens på proxysiden

`credentials` kobler en tillatt host/443 og auth-header til en navngitt
vertsvariabel. `env: klient=kilde` leser høyresiden fra operatørens prosessmiljø;
`env: klient` bruker samme navn på begge sider. Verdien er en rå nøkkel,
uten Bearer-prefiks.

Ved opprettelse får agentens klientvariabel en unik plassholder når kilden
har verdi, ellers en tom streng. Den ekte nøkkelen gis bare til proxyens
miljø og inngår ikke i config, policy, tilstand eller argumenter. Agenten får
offentlig CA/bundle; privat CA forblir på den betrodde siden. Docker lagrer
proxyens miljø som metadata, som kan leses ved fullt utbrudd til tjenestebrukeren.
Se [praktisk oppsett](usage.md#api-tokens-i-proxyen).

### Krav til headerutskifting

En nøkkelregel må også finnes i `network.allow`. Samme klientnavn må vise
til samme kilde i alle miljøets regler. Flere klientnavn kan dele kilde og
får egne plassholdere. Bare klientnavnet valideres mot reserverte runtime-navn;
konfigurasjonen er betrodd og skal ligge utenfor agentens skrivbare mapper.

Tillatte auth-headere er Authorization, X-API-Key og CONTEXT7_API_KEY.
Match bare hele plassholderen eller den etter Bearer-prefiks. Prefikset
beholdes; dupliserte relevante headere og tvetydige aliaser avvises. Navn
normaliseres til små bokstaver med `_` lik `-`. Bare GET, HEAD, POST, PUT,
PATCH, DELETE og OPTIONS tillates på avlyttet trafikk; deklarerte trailere
og Upgrade avvises. URL/body omfattes ikke av utskifting.

CONNECT-destinasjon, SNI og Host/authority må være konsistente for hver
request, også på gjenbrukte forbindelser. Upstream bruker godkjent pin og
validert sertifikatnavn; ingen DNS-/proxy-fallback eller automatisk redirect.
En eksplisitt tom regel beholder TLS-inspeksjon, men kan ikke ha ekte token.
Vanlige requests uten plassholder kan videresendes uten nøkkelinnsetting.

### Levetid og tilbakekalling

Miljøets plassholderkart lagres uten ekte nøkler. Det er fast gjennom
agentcontainerens levetid. Tom/ikke-tom overgang krever gjenskaping;
`remove` sletter containerlaget, men beholder eksplisitte katalog-/volummounts.

Apply sjekker først profil, klientnavn, mounts og nettverk. Avslag her endrer
ikke eksisterende proxy; feilen viser `proxy stop` for tilbakekalling.
Etter denne kontrollen fjernes gammel proxy før tokenvalidering og kontroll
av tilgjengelighet. Senere feil gjenoppretter ikke gamle nøkler. Gjentatt
start av et uendret kjørende miljø leser ikke kildene på nytt.

`proxy stop` er eksplisitt lokal tilbakekalling. Unset alene endrer ikke
kjørende proxyer. Tilbakekalling hos API-leverandøren er en separat operasjon.
Fjernes nøkkelregelen eksplisitt, kan nettverkspolicyen igjen tillate vanlig
tunnel. Den ekte nøkkelen settes aldri inn i en slik tunnel.
