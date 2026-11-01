# Arkitekturvalg for Agentbox

Agentbox 1.0.1 bruker en felles tjenestebruker, prosjekt-ACL-er og en proxy per
miljø. Valgene under forklarer hvordan isoleringen håndheves og hvilke
begrensninger den gir. Prøvegrunnlaget finnes i [teststatus](test-results.md),
og produktkontrakten i [spesifikasjonen](specification.md).

## Kontroll og identitet

Python-CLI kjøres som utvikleren. Docker-operasjoner går gjennom en fast
kontrollhjelper kjørt som `agentbox` med en avgrenset sudo-regel. Forespørsler
sendes som JSON på stdin. Root-installasjonen og Python-avhengighetene ligger
under `/opt/agentbox`; hjelperen bruker isolert Python-oppstart og fast socket.

Utviklerens ACL-journal ligger separat i `/var/lib/agentbox-operator` med modus
0700. Agentmiljøene får ingen av disse katalogene montert inn.

## Prosjektroten som grense for tilbakekalling

Prosjektroten må eies av utvikleren. Registrering gir `agentbox` tilgang til
innholdet; tilbakekalling legger `user:agentbox:---` på roten. En navngitt
bruker-ACL prioriteres foran gruppe- og andre-rettigheter. Prøven bekrefter at
denne sperren blokkerer filtilgang også når `agentbox` eier filen under roten.

Alle berørte containere må være stoppet først. Overlappende registreringer
avvises i versjon 1.0.1, slik at en separat registrert undermappe ikke krever tilgang
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

Et katalogmount kan eksponere en Unix-socket på verten. Det er demonstrert
med standardprofilen i laben. Agentprofilen er derfor en strengere variant
av en revisjonslåst Moby-profil; standard syscallbegrensninger beholdes.

Nye `AF_UNIX`-sockets, datagram-socketpar, `socketcall` og io_uring-operasjoner
blokkeres. Tilkoblede stream-socketpar beholdes for privat prosesskommunikasjon;
prøven bekrefter at de ikke kan kobles om til vertens filsystemsocket.
Profilen gjelder også `docker exec`. Python `asyncio` fungerer i prøven.

Verktøy som trenger filsystem- eller abstrakte Unix-sockets støttes ikke av
denne imageprofilen. Dette er en reell kompatibilitetsbegrensning, ikke et
signal om at mer privilegier skal slås på automatisk.

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

Den interne Docker-resolveren er testet mot en kontrollert DNS-tjeneste uten
observert ekstern videresending. Oppgraderinger av Docker/RootlessKit krever
ny gjennomkjøring av denne prøven.

## Codex-oppstart i 1.0.1

Utviklingsimaget har en launcher som kjører Codex med `--no-daemon`.
Codex 0.166.0 forsøkte ellers å starte en delt app-server ved gjentatt oppstart,
og dette feilet med `Operation not permitted` under isoleringsprofilen.
Det konkrete avslåtte systemkallet er ikke kartlagt. To oppstarter uten
bakgrunnsserver viste grensesnittet, og innloggingsstatus var fortsatt gyldig.
Rettelsen beholder seccomp-profilen og endrer ikke felles image- eller nettverkslogikk.

## Logger og lagring

Kontrollverktøyet logger ikke forespørsler eller nøkkelverdier. Proxyens
tilgangslogg viser bare destinasjon og resultat. Agentens egne utdata streames
og lagres i private, roterte logger; de kan inneholde det agenten skriver.

Stopp og gjenopptak med uendret konfigurasjon bevarer containerlaget og
Codex-innlogging. Separat profilvolum er ikke implementert.
Endret agentprofil eller vertsadresse krever eksplisitt fjerning og ny
opprettelse. Nettverk/tokenregler aktiveres med proxy apply; gjenopptak av
stoppet Go-miljø validerer og fastlåser DNS på nytt.
Fjerning sletter laget og miljøets logger. Prosjektfiler, registreringer og ACL-er består til egne
operasjoner endrer dem. Kjøremiljøer gjenopptas ikke automatisk etter vertsreboot.

## Go-proxy og miljøbaserte tokens

En avgrenset Go-proxy med goproxy håndterer nøkkelutskifting. Squid og
mitmproxy ble vurdert; vi valgte Go for å samle den konkrete destinasjons-
og headerpolicyen i en liten, testbar implementasjon. HTTP/TLS håndteres av
bibliotek og standardbibliotek, ikke egen protokoll- eller kryptokode. Én prosess per miljø
håndhever eksisterende destinasjons-/IP-policy, selektiv TLS-avlytting og
plassholderutskifting i headere. Ingen parallell proxykjede eller separat autorisasjonsdatabase.
Proxyen kjører fortsatt uten root i containeren og får bare egne PKI-filer.

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
Feil etter stopp gir ingen fallback til gammel nøkkel. Read-only filsnapshots
av privat CA ligger under hostkatalog0700; token har ingen filsnapshot.

Tilfeldige plassholdere er ufarlige utenfor miljøets proxy. Tilgang fra innsiden
av et autorisert miljø kan likevel forbruke den ekte nøkkelens rettigheter.
Dette er skjerming av nøkkelverdien og kontroll av destinasjon, ikke begrensning
av hvilke API-operasjoner agenten kan utføre. TLS-interception er nødvendig
for å endre HTTPS-headere og velges bare av eksplisitte nøkkelregler.

Tomme referanser bruker samme regeltype med tom plassholder. De beholder
TLS-inspeksjon for å unngå at manglende nøkkel åpner en tunnel. Nye klientnavn
og tom/ikke-tom overgang krever gjenskaping fordi Docker sitt prosessmiljø er
fast; ingen shell-hook eller egen oppdateringstjeneste innføres.
