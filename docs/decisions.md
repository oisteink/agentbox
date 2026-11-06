# Arkitekturvalg for Agentbox

Agentbox bruker en felles tjenestebruker, prosjekt-ACL-er og en proxy per
miljø. Valgene under forklarer hvordan isoleringen håndheves og hvilke
begrensninger den gir. Prøvegrunnlaget finnes i [teststatus](test-results.md),
og produktkontrakten i [spesifikasjonen](specification.md).

## Kontroll og identitet

Python-CLI kjøres som utvikleren. Docker-operasjoner går gjennom en fast
kontrollhjelper kjørt som `agentbox` med en avgrenset sudo-regel. Forespørsler
sendes som en JSON-header på stdin; resten brukes til bygg eller kommandoinput.
JSON Lines skiller kontrollresultat fra agentens stdout/stderr uten en ekstra
socket eller tjeneste. CLI-en krever ett terminalresultat og velger menneske-
eller JSON-visning. Poll-basert videresending hindrer at input venter på output
som først kan produseres etter at mer input er sendt. Root-installasjonen og Python-avhengighetene ligger
under `/opt/agentbox`; hjelperen bruker isolert Python-oppstart og fast socket.

Utviklerens ACL-journal ligger separat i `/var/lib/agentbox-operator` med modus
0700. Agentmiljøene får ingen av disse katalogene montert inn.

## Lokale imageoppskrifter

Agentimages har lokale Dockerfiles under utviklerens `~/.config/agentbox/images/`.
Katalogen er byggkontekst; vanlige FROM, COPY og hjelpeskript brukes uten et
eget byggformat eller imageregister. Malene følger Python-pakken og kopieres
bare ved eksplisitt `image new`. Oppskrifter eies og redigeres av utvikleren.
Proxyimaget er en intern komponent som installeren bygger når det mangler.
Eksisterende image beholdes; `proxy build` brukes til ombygging.

CLI-en pakker konteksten som tar uten å følge lenker og sender den etter en
JSON-header. Kontrollhjelperen autentiserer først og mellomlagrer i private,
midlertidige filer. Ingen generell tilgang til utviklerens hjem eller nye
prosjekt-ACL-er trengs. Utpakking bruker Pythons datafilter; lenker ut av
konteksten og spesialfiler avvises. Docker bygger den midlertidige katalogen,
slik at Docker selv behandler .dockerignore. BuildKits upload-kontekst
filtrerer ikke ignore-reglene. Hele konteksten overføres til kontrollsiden
før builderen filtrerer filer.

En fast tag avledes fra navnet, `agentbox-image-NAVN:local`. Docker-labels
identifiserer installasjon og oppskrift; et tilfeldig image med samme tag
aksepteres ikke ved start. Oppskriftskatalogene gir oversikten over lokale
oppskrifter; Docker gir bygde ID-er og brukere. Ingen ekstra tilstandsfil.

Bygg og fjerning undersøker alle containere og sammenligner eksakt image-ID.
Avledede images inngår ikke i brukssjekken. Stoppede containere regnes som
brukere. Kontrollsidens operasjonslås serialiserer sjekken og mutasjonen
med start/remove. Dette forutsetter
at Docker-instansen administreres gjennom kontrollhjelperen.

Containerlaget følger vanlig Docker-livssyklus. Fjern miljøene før ombygging,
og behold nødvendige arbeidsfiler i mounts. Fjerning sletter containerlaget,
inkludert hjem og innlogging.

Kildegrunnlag: [Docker-byggkontekst](https://docs.docker.com/build/concepts/context/),
[ancestor-filter](https://docs.docker.com/reference/cli/docker/container/ls/),
[Buildx-ruting](https://github.com/docker/buildx/blob/master/build/opt.go) og
[BuildKit-kontekst](https://github.com/moby/buildkit/blob/master/frontend/dockerui/config.go).

## Prosjektroten som grense for tilbakekalling

Prosjektroten må eies av utvikleren. Registrering gir `agentbox` tilgang til
innholdet; tilbakekalling legger `user:agentbox:---` på roten. En navngitt
bruker-ACL prioriteres foran gruppe- og andre-rettigheter. Prøven bekrefter at
denne sperren blokkerer filtilgang også når `agentbox` eier filen under roten.

Alle berørte containere må være stoppet først. Overlappende registreringer
avvises, slik at en separat registrert undermappe ikke krever tilgang
gjennom en tilbakekalt rot. Delte foreldrekataloger mellom søskenprosjekter
håndteres med referanser i journalen.

Innholdets ACL-er beholdes ved tilbakekalling, og eierskap overføres ikke.
Garantien gjelder tilgangen gjennom den registrerte roten; hardlenker,
filflytting eller andre kopier utenfor roten må ikke brukes som en alternativ
tilgangsvei. Eksisterende hardlenker avvises før tildeling. Manuelle flyttinger
av prosjektinnhold på verten er en betrodd operasjon og krever ny vurdering.

Når en ACL-maske må utvides for samarbeid, bevares andre brukeres og gruppers
effektive rettigheter. Tidligere maskerte biter kan trimmes fra rå ACL-oppføringer.
Reparasjon kjøres som henholdsvis utvikleren og tjenestebrukeren for filer de
selv eier. Ingen rekursiv root-operasjon eller `chown` brukes i daglig drift.

## Unix-sockets og seccomp

Et katalogmount kan eksponere en Unix-socket på verten. Agentprofilen
blokkerer nye Unix-sockets og bygger på en revisjonslåst Moby-profil
med standard syscallbegrensninger.

Nye `AF_UNIX`-sockets, datagram-socketpar, `socketcall` og io_uring-operasjoner
blokkeres. Tilkoblede stream-socketpar beholdes for privat prosesskommunikasjon.
Profilen gjelder også `docker exec`. Enkel bruk av Python `asyncio` er prøvd i lab.

Verktøy som trenger filsystem- eller abstrakte Unix-sockets støttes ikke av
denne imageprofilen. Isoleringsprofilen utvides ikke automatisk for slike verktøy.

## Nettverk, DNS og vertsadresser

Hvert miljø får et internt `isolated` bridge-nettverk og en egen Go-proxycontainer
med et separat eksternt nettverk. IPv6 er deaktivert for agenten. Ingen porter
publiseres, og IP-videresending slås av i proxyen.

Tillatte navn løses på kontrollsiden ved oppstart. Alle svar må være offentlige
og ikke tilhøre verten. Én IPv4-adresse per navn fastlåses i Go-proxyens policy;
proxyen har ingen ekstern DNS-fallback. Dette avviser interne adresser og
hindrer at DNS-endringer etter oppstart endrer tunnelens destinasjon.

Ulempen er at serverflytting kan kreve eksplisitt proxy apply.
En systemd-brukertjeneste utenfor agentens namespace overvåker vertens
adresseoversikt og stopper miljøer når den endres. Den sjekker omtrent hvert
sekund og deler operasjonslås med kontrollverktøyet. Dette er ingen atomisk
brannmurregel for samtidige nettverksendringer; vertens nettverksadministrasjon
er betrodd, og stabil vertskonfigurasjon er forutsetningen under normal kjøring.

Agentcontaineren opprettes med `--dns 127.0.0.1` på det lukkede nettverket.
Ekstern DNS-videresending gjennom Docker-resolveren trenger en oppdatert
mottakerprøve på aktuell Docker/RootlessKit; se [teststrategien](testing.md#åpne-verifikasjonshull).

## Codex-oppstart

Codex-launcheren bruker `--no-daemon` fordi oppstart av delt app-server
feiler under isoleringsprofilen. Agenten bruker samme seccomp- og nettverksregler
som andre images. Det konkrete avslåtte systemkallet er ikke kartlagt.

## Logger og lagring

Kontrollverktøyet logger ikke forespørsler eller nøkkelverdier. Proxyens
tilgangslogg viser bare destinasjon og resultat. Agentens egne utdata streames
og lagres i private, roterte logger; de kan inneholde det agenten skriver.

Med `persistent: true` bevarer stopp og gjenopptak med uendret konfigurasjon
containerlaget, verktøyoppsett og innlogging. Separat profilvolum er ikke implementert.
Endret agentprofil eller vertsadresse krever eksplisitt fjerning og ny
opprettelse. Nettverk/tokenregler aktiveres med proxy apply; gjenopptak av
stoppet miljø validerer og fastlåser DNS på nytt.
Fjerning sletter laget og miljøets logger. Prosjektfiler, registreringer og ACL-er består til egne
operasjoner endrer dem. Kjøremiljøer gjenopptas ikke automatisk etter vertsreboot.

## Midlertidige miljøer

`run` gjenbruker opprettelse, terminalkjøring og fjerning. Miljøfiler med
`persistent: false` bruker samme opprydding etter shell. Start klargjør
fortsatt i bakgrunnen, mens stop fjerner miljøet. En shell-reservasjon under
lås forhindrer at to shell-sesjoner deler ansvaret for opprydding. Reservasjonen
nullstilles ikke ved start eller proxy apply; hardt avbrudd krever eksplisitt
fjerning. Ingen ny daemon eller filkopiering er nødvendig. Kommandoen kjører
uten global operasjonslås; oppryddingen verifiserer opprettet agent-ID mot
ny tilstand under lås. Dermed kan andre miljøer brukes samtidig, uten at
en samtidig remove/gjenskaping med samme navn rammes av feil opprydding.
SIGINT utsettes under opprettelse og fjerning. CLI-en venter på
hjelperens opprydding ved avbrudd. Ingen ekstra daemon er nødvendig.

## Go-proxy og miljøbaserte tokens

Go-proxyen bruker goproxy og Go sitt standardbibliotek til HTTP/TLS.
Én prosess per miljø håndhever destinasjons-/IP-policy, selektiv TLS-avlytting
og plassholderutskifting i headere. Proxyen kjører uten root i containeren
og får bare egne PKI-filer.

Tokens kommer fra eksplisitt navngitte variabler i operatørens miljø. De gis
til proxyens miljø gjennom kontrollhjelperen uten verdier i argumenter eller
konfigurasjonsfiler. Docker lagrer miljøet i sine metadata; dette beskytter
ikke mot fullt utbrudd til tjenestebruker og Docker-instans. Agenten får bare
offentlig CA-katalog med komplett bundle og genererte plassholdere i de
refererte variabelnavnene, ikke privat CA eller ekte tokenmiljø. Kartet lagres
uten hemmeligheter i miljøtilstanden og beholdes ved proxybytte. Bare eksakt
plassholder eller Bearer-formen matcher en regel. Nye tokenvariabler krever
gjenskaping av container; ingen egen oppdateringsmekanisme for shellmiljø.

Proxyen gjenskapes ved endringer; gamle forbindelser lukkes før aktivering.
Feil etter stopp gir ingen fallback til gammel nøkkel. Read-only snapshots av privat CA ligger i en vertskatalog med modus 0700.
Ekte tokens lagres ikke i filsnapshots.

Tilfeldige plassholdere er ufarlige utenfor miljøets proxy. Tilgang fra innsiden
av et autorisert miljø kan likevel forbruke den ekte nøkkelens rettigheter.
Dette er skjerming av nøkkelverdien og kontroll av destinasjon, ikke begrensning
av hvilke API-operasjoner agenten kan utføre. TLS-interception er nødvendig
for å endre HTTPS-headere og velges bare av eksplisitte nøkkelregler.

Tomme referanser bruker samme regeltype med tom plassholder. De beholder
TLS-inspeksjon for å unngå at manglende nøkkel åpner en tunnel. Nye klientnavn
og tom/ikke-tom overgang krever gjenskaping fordi Docker sitt prosessmiljø er
fast; ingen shell-hook eller egen oppdateringstjeneste innføres.

## Teststrategi

Produktkrav og brukerflyter styrer testene. Rene regler prøves lokalt, mens
installerte CLI-scenarier undersøker prosessgrensene, ACL og Docker. Proxyen
prøves mot kontrollerte TLS-mottakere. Vi beholder smale erstatninger for
eksterne kall og bruker ekte lokale prosesser/filer der det gir relevant bevis.
En generell Docker-simulator vil kreve en ekstra modell av runtime-oppførselen.

Livssyklusprøvene har eget oppsett og opprydding per scenario. Det gir separate
resultater når én grunnfunksjon feiler. Den sammenhengende tokenlivssyklusen
beholdes i ett labskript fordi overgangene er selve prøven. Begge løp skal
rapportere feil ved mislykket opprydding. Bevaring undersøkes med agent-ID og
en fil i hjemmet; terminalinnlesing med et transformert svar fra prosessen.

Enkle shellinnganger samler lokale kontroller og labkjøring. Laben installerer
og bygger aktuell kilde, sammenligner installerte filer og registrerer
image-ID-er. Et labløp med bare hoppede tester er mislykket. Testantall og
dekningsprosent er ikke leveransemål. Kravdekning og åpne hull vedlikeholdes i
[teststrategien](testing.md); nye observasjoner føres i [teststatus](test-results.md).

Skannere hopper over kjente nestede mountpunkter før de åpnes. Tjenestebrukeren
skal ikke trenge lesetilgang til en mappe utenfor prosjektets valgte filsystem
for å starte miljøet. Samme regel gjelder avinstallasjonens inspeksjon.
