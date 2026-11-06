# Arkitekturvalg for Agentbox

Agentbox bruker en felles tjenestebruker, katalog-ACL-er og en proxy per
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

Brukerens oppskrifter under XDG/~/.config/agentbox/images er både byggkontekst
og lokale maler. En lokal default velges når ingen mal er angitt. Medfølgende
maler bruker pakkens installasjonseide templates-katalog, på verten under
/opt/agentbox/lib/agentbox/templates. Dette gir reinstallasjon ett kjent
kodeområde å gjenopprette, mens brukerens filer beholdes. Ingen ekstra
systemkatalog eller eget malregister trengs. Kopier beholder kontekst/lenker
uten binding til senere endringer i kilden.

CLI pakker tar uten å følge lenker. Kontrollhjelperen autentiserer før den
leser, mellomlagrer privat og bruker Pythons datafilter. Docker bygger den
utpakkede katalogen og behandler .dockerignore selv. Hele konteksten overføres
før builderens filtrering; ingen generell ACL-tilgang til brukerhjemmet kreves.

Inputstempelet hasher medlemmer og filbytes, uten mtime/eier/padding, og lagres
som imagelabel. Samme funksjon beregner lokal status og faktisk mottatt input.
Hele input teller konservativt, også ignorerte filer. Det kan gi ekstra bygg,
men krever ingen nesten-lik Dockerignore-parser eller ny tilstandsdatabase.
Registryendringer i uendret FROM-tag inngår ikke i denne lokale kontrollen.

En fast tag, agentbox-image-NAVN:local, gir gjeldende image. Bruk følger
identitetsbundne agentressurser, agentens egne containerlabels, den opprinnelige
Config.Image-taggen og eksakt aktuell image-ID. Dermed skjuler tagflytting
ikke Agentbox-brukere, mens arvede image-labels alene ikke sperrer avledede
images. Bygg sperres av kjørende bruk, remove også av stoppede brukere.
Kontrollåsen dekker sjekk og mutasjon.

Start/run/exec deler klargjøring og bygger ved behov. Kontrollstart sjekker
ønsket digest under lås: Et foreldet CLI-øyeblikksbilde kan ikke starte et
gammelt image etter at miljøet har stoppet. Samme handling prøver klargjøring
på nytt ved image_outdated, inntil tre forsøk. Run holder stdin tilbake til
intern input_ready rett før execute. Retry krever at ready ikke er mottatt
og at brukeren ikke avbrøt; etter ready retries aldri. Offentlig JSON har ett
sluttresultat. Exec bruker valgt full agent-ID, så et generasjonsbytte før
kommandoen avvises fremfor å sende den til et annet oppsett.

Pending beholder kjørende agent og proxy/policy, også når proxyen mangler.
Exec reaktiverer ikke en stoppet proxy på kjørende agent. Eksplisitt start kan
reparere proxy bare ved uendret profil/digest/klientmiljø. Adressevakten kan
fortsatt stoppe miljøet før pending-retur. Profil, mounts, tokenverdier, DNS
og policy valideres før et stoppet lag erstattes. Uendret stoppet miljø
beholder laget; endret image/config/klienttilstand/adresser gir ny container.
Data som skal overleve dette må ligge i eksplisitte mounts.

Grunnlag: [Docker-byggkontekst](https://docs.docker.com/build/concepts/context/),
[Buildx](https://docs.docker.com/reference/cli/docker/buildx/build/) og
[tarfile/datafilter](https://docs.python.org/3.12/library/tarfile.html).
Proxyimaget er en intern komponent med separat bygg-/oppgraderingsregel.

## Katalogroten som grense for tilbakekalling

Katalogroten må eies av utvikleren. Registrering gir `agentbox` tilgang til
innholdet; tilbakekalling legger `user:agentbox:---` på roten. En navngitt
bruker-ACL prioriteres foran gruppe- og andre-rettigheter. Prøven bekrefter at
denne sperren blokkerer filtilgang også når `agentbox` eier filen under roten.

Tilbakekalling varsler om aktive brukere og åpne håndtak, og stopper ingen
miljøer. En registreringssperre hindrer nye monteringer; katalogroten får
også deny. Flytting av innhold utenfor den registrerte roten er en betrodd
vertsoperasjon og må vurderes separat.

Navngitte local-volumer er eksplisitte, merkede kilder. De bruker samme
source-navnerom som kataloger, uten en generell driver-/lagringsabstraksjon.
Volume-nocopy gir et tomt nytt volum; ingen utilsiktet kopiering fra imaget.
Siden stoppede containere fortsatt refererer til volumet, må volum-remove
fjerne deres miljøer og containerlag. Konsekvensen krever navngitt samtykke
bundet til registrering og ressurs-ID-er. Kildebrukere beregnes fra faktisk
Docker-metadata under kontrollåsen, og fremmede containere avvises.

Katalog-remove deler ACL-arbeidet mellom fileierne og krever komplett inventar
før registeret glemmes. Operatørjournalen lagres før siste kontroll-RPC.
Removing-tilstanden sperrer gjenåpning mens feil rettes eller et avbrudd prøves
igjen. Traverserings-ACL-er gjenopprettes fra urørt snapshot; ved manuelle
endringer fjernes bare serviceoppføringer, uten å overskrive andre endringer.

Eierskifte krever CAP_CHOWN. Vanlig remove beholder derfor eierskap og
operatør-ACL på agentbox-eide filer. Tjenestebrukerens eiertilgang kan bestå,
og etter avregistrering inngår filene ikke i uninstall sin eierskapsrydding.
Dette oppgis i fjerningsresultatet. En ny root-hjelper ville utvide
privilegiegrensen; kopiering/erstatning ville endre inoder og filmetadata.
Begge unngås. Administratorstyrt uninstall overfører bare registrerte kataloger.

Grunnlag: [Docker-volumer](https://docs.docker.com/engine/storage/volumes/),
[volumfjerning](https://docs.docker.com/reference/cli/docker/volume/rm/),
[chown](https://man7.org/linux/man-pages/man2/chown.2.html) og
[POSIX ACL](https://man7.org/linux/man-pages/man5/acl.5.html).

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
containerlaget, verktøyoppsett og innlogging. Profiler i eksplisitte katalog-/volummounts
lever uavhengig av containerlaget.
Endret image, konfigurasjon, klientvariabeltilstand eller vertsadresse gir
ny container ved neste oppstart av stoppet miljø. Nettverk/tokenregler aktiveres med proxy apply; gjenopptak av
stoppet miljø validerer og fastlåser DNS på nytt.
Fjerning sletter laget og miljøets logger. Filer i katalogmounts, registreringer og ACL-er består til egne
operasjoner endrer dem. Kjøremiljøer gjenopptas ikke automatisk etter vertsreboot.

## Automatisk livssyklus

Start/exec bruker én kontrolloperasjon for klargjøring og registrering under
samme lås. Hver kjøring har en egen sesjon; en tilfeldig generation-ID skiller
kjøreperioder selv når Docker beholder container-ID ved restart. Siste
avslutning leser aktuell sessions-map og keep-running-latch. Dermed kan enhver
kjøring sette flagget sent, og en tidligere avslutning kan ikke overstyre det.
Stop invaliderer perioden før Docker-stopp. Finally og watcher bruker samme
reap/finalize og starter aldri nye ressurser.

Klient og helper identifiseres med PID, starttime, boot-ID og UID. Dette kan
lagres atomisk og observeres av eksisterende watcher; en ny tjeneste for
pidfd-er eller refcount er unødvendig. Ukjent proc-observasjon bevarer sesjonen.
Kravet om lesbar proc-metadata begrenser bruk med restriktiv hidepid.
Keep-running bevarer containeren også ved klientkrasj; det lover ikke individuell
stopp av alle agentprosesser. Run bruker samme mekanisme med unik instans og
persistent=false, så parallelle kjøringer ikke deler oppryddingsansvar.

En kort launchfase under vanlig lås bekrefter konkret Docker-exec-PID eller
endelig ExitCode før låsen slippes. Docker sender exec_start før prosessen
finnes; eventet brukes bare til å finne ID ved rask exit. En liten read-only
klient mot fast verifisert Unixsocket leser rå JSON og beholder nullable
ExitCode. Eksisterende DockerCLI håndterer fortsatt PTY, resize og strømming.
Dette krever mindre ny transportkode enn ExecCreate/Start-hijack i Python.
[Moby exec](https://raw.githubusercontent.com/moby/moby/master/daemon/exec.go),
[Docker 28 inspect](https://raw.githubusercontent.com/moby/moby/v28.0.0/daemon/inspect.go).

Separat launch-intent før Popen dekker helperkrasj og uklart backendutfall.
Docker-routerens hijack bruker en bakgrunnskontekst; terminert DockerCLI er
derfor ikke et kanselleringsbevis. Ukjent utfall stopper miljøet og sperrer
samme container-ID frem til bekreftelse eller faktisk fjerning. Persistent
lag slettes ikke automatisk for å komme rundt usikkerhet. Loggkatalog-FD
binder senere skriving til riktig katalog selv etter remove/gjenskaping.
[Moby-router](https://raw.githubusercontent.com/moby/moby/master/daemon/server/router/container/exec.go).

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
og tom/ikke-tom overgang krever ny container fordi Docker sitt prosessmiljø er
fast. Start av stoppet miljø håndterer erstatningen; proxy apply avviser slik
endring på eksisterende agent. Ingen shell-hook eller oppdateringstjeneste trengs.

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
skal ikke trenge lesetilgang til en mappe utenfor den valgte katalogens filsystem
for å starte miljøet. Samme regel gjelder avinstallasjonens inspeksjon.
