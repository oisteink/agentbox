# Agentbox på C4 nivå 1 og 2

Agentbox kjører kodeagenter med valgte prosjektmapper og kontrollert utgående
nettverkstilgang. C1 viser systemet og omgivelsene; C2 viser
kjørbare deler, datalagre og forbindelsene mellom dem.

En C4-container betyr et program eller et datalager. Begrepet er bredere enn
en Docker-container: CLI-en og kontrollhjelperen er også C4-containere.
Alle interne deler kjører på samme Linux-vert. Test-VM-en er et labmiljø og
inngår ikke som et krav i produktarkitekturen.

## C1 systemkontekst

![C1: Agentbox og omgivelsene](diagrams/agentbox-context.svg)

<details>
<summary>PlantUML-kilde</summary>

```plantuml
@startuml agentbox-context
!include <C4/C4_Context>
LAYOUT_LEFT_RIGHT()
title Agentbox - C1 systemkontekst

Person(developer, "Bruker", "Velger arbeidsmapper, agentverktøy og hvilke tjenester miljøene får bruke.")
System(agentbox, "Agentbox", "Kjører isolerte agentmiljøer med avgrenset filtilgang og kontrollert utgående trafikk.")
System_Ext(workspace, "Vertens filsystem", "Arbeidsmapper som brukeren deler med ett eller flere agentmiljøer.")
System_Ext(services, "Tjenester brukt av agentene", "Eksempelvis eksterne API-er, MCP-tjenester, modelltjenester, kodeverter og pakkeregistre.")
System_Ext(supply, "Kilder for kjøremiljøer", "Leverer containerimages og avhengigheter når Agentbox bygger images.")

Rel(developer, agentbox, "Konfigurerer tilgang og bruker agentmiljøene")
Rel(developer, workspace, "Leser og redigerer egne arbeidsfiler")
BiRel(agentbox, workspace, "Leser og endrer eksplisitt delte mapper")
Rel(agentbox, services, "Agenttrafikk til eksplisitt tillatte destinasjoner")
Rel(agentbox, supply, "Henter baseimages og byggeavhengigheter ved klargjøring")
SHOW_LEGEND()
@enduml
```

</details>

De eksterne tjenestene grupperes etter hvordan de inngår i Agentbox:
agentenes arbeid og klargjøring av kjøremiljøer. Dette er roller, ikke faste
leverandører eller konfigurerte integrasjoner. Samme eksterne system kan
brukes i begge roller, eksempelvis et pakkeregister.

API-er og MCP-tjenester kan brukes når miljøets destinasjonsregler tillater
det. Agentbox tilbyr ikke selv et MCP-grensesnitt. Agenttrafikk avvises som
standard; imagebygging og henting av baseimages skjer på kontrollsiden utenfor denne
nettverkspolicyen. C2 viser hvilke deler som håndterer de to trafikkveiene.

## C2 containere

![C2: Agentbox sine programmer, datalagre og forbindelser](diagrams/agentbox-containers.svg)

<details>
<summary>PlantUML-kilde</summary>

```plantuml
@startuml agentbox-containers
!include <C4/C4_Container>
LAYOUT_TOP_DOWN()
title Agentbox - C2 containere

Person(developer, "Bruker", "Bruker personlig Linux-konto.")
ContainerDb_Ext(projects, "Valgte prosjektmapper", "Vertens filsystem", "Eies av utvikleren. ACL gir agentbox tilgang; mounts velges per miljø.")
System_Ext(services, "Tjenester brukt av agentene", "Eksterne API-er, MCP-tjenester, modelltjenester, kodeverter og pakkeregistre; tilgang velges per miljø.")
System_Ext(registry, "Kilder for kjøremiljøer", "Images og byggeavhengigheter; tilgang fra betrodd kontrollside.")

System_Boundary(agentbox, "Agentbox") {
    Container(cli, "abx", "Python; utviklerens UID", "Validerer miljøfiler, håndterer imageoppskrifter og administrerer utviklerens ACL-endringer.")
    ContainerDb(recipes, "Miljøfiler og imageoppskrifter", "Utviklerens filer", "~/.config/agentbox; YAML og lokale Dockerfiles med byggkontekst.")
    ContainerDb(journal, "ACL-journal", "Private JSON-filer", "/var/lib/agentbox-operator; eies av utvikleren.")
    Container(control, "Kontrollhjelper", "Python; agentbox UID", "Bygger images og administrerer prosjekter, miljøer, proxy og terminaler.")
    Container(uninstall, "Avinstallering", "scripts/uninstall.sh; Bash / Python; root", "Kjøres fra repoet. Rydder ACL-er og overfører prosjektfiler til utvikleren før installasjonen fjernes. ")
    Container(watch, "Adressevakt", "Python / systemd; agentbox UID", "Stopper miljøer ved endrede vertsadresser.")
    ContainerDb(state, "Kontrolltilstand og policy", "Private filer; agentbox UID", "/var/lib/agentbox/state; miljøregister, proxyregler, miljø-CA og logger.")
    Container(docker, "Rootless Docker-instans", "Docker Engine / RootlessKit", "Egen daemon som agentbox; administrerer containere, nettverk og images.")

    Boundary(environment, "Arbeidsmiljø - ett av flere", "Agent og proxy per miljø") {
        Container(agent, "Kodeagent og utviklingsverktøy", "Docker; UID 0 i containeren", "Upålitelig agentkode i valgt lokalt image. Lukket nettverk, valgte mounts og streng seccomp.")
        Container(proxy, "Utgående proxy", "Docker / Go; UID 10001", "Betrodd proxy med ett grensesnitt internt og ett eksternt. Eksakte destinasjoner, pinnede IP-er og selektiv TLS-avlytting med tokenutskifting.")
        ContainerDb(home, "Agentens hjem og innlogging", "Containerens skrivbare lag", "/home/agent; verktøyoppsett og innlogging. Stopp bevarer; remove og avsluttet run sletter.")
    }
}

Rel(developer, cli, "Administrerer og åpner terminaler", "Lokale kommandoer")
Rel(developer, projects, "Redigerer", "Editor / filsystem")
Rel(cli, recipes, "Leser miljøfiler og Dockerfiles; lager imageoppskrifter", "Filsystem")
Rel(cli, journal, "Registrerer og avstemmer ACL-endringer", "Filsystem")
Rel(cli, projects, "Tildeler og tilbakekaller tilgang som fileier", "POSIX ACL")
Rel(cli, control, "Sender operasjoner og eksplisitt refererte tokens", "Avgrenset sudo; JSON og byggkontekst på stdin")
Rel(developer, uninstall, "Kjører avinstallasjon eller forhåndsvisning fra repoet", "sudo scripts/uninstall.sh")
Rel(uninstall, projects, "Overfører agentbox-eide filer og rydder ACL-er", "Avgrenset filsystemtilgang; ingen symlinkfølging")
Rel(uninstall, state, "Leser registeret før filrydding og sletting", "Privat tilstand og operasjonslås")
Rel(uninstall, journal, "Avstemmer og rydder foreldrenes ACL-er", "Privat journal og lås")
Rel(control, projects, "Reparerer ACL på filer eid av agentbox", "POSIX ACL")
Rel(control, state, "Lagrer tilstand, policy og agentutdata", "Filsystem")
Rel(watch, state, "Leser miljøer og oppdaterer status", "Filsystem og felles lås")
Rel(control, docker, "Styrer containere; gir kun proxyen tokenmiljø", "Docker CLI; fast Unix-socket")
Rel(watch, docker, "Stopper berørte containere", "Docker CLI; samme socket")
Rel(docker, agent, "Oppretter og styrer livssyklus", "Docker runtime")
Rel(docker, proxy, "Oppretter og styrer livssyklus", "Docker runtime")
Rel(docker, registry, "Henter baseimages og bygger", "Betrodd kontrolltrafikk")
Rel(agent, projects, "Leser og endrer valgte mapper", "Eksplisitte bind mounts; rw eller ro")
Rel(agent, home, "Lagrer profil og innlogging", "Filsystem i containerlaget")
Rel(agent, proxy, "Sender utgående forespørsler", "HTTP / CONNECT via lukket nettverk")
Rel(proxy, state, "Leser policy og miljøets private CA", "Read-only bind mounts")
Rel(agent, state, "Leser kun offentlig CA og bundle", "Read-only mount av offentlig underkatalog")
Rel(proxy, services, "Kobler til tillatt destinasjon", "HTTP / TLS-tunnel eller avlyttet HTTPS")
SHOW_LEGEND()
@enduml
```

</details>

### Grensene som betyr mest

- Den stiplede systemgrensen angir produktets omfang. Miljøgruppen samler
  agent, proxy og hjemmekatalog; nettverkstilgang følger pilene og nodenes beskrivelser.
- Utviklerkontoen og `agentbox` er separate vertsbrukere. Kontrollhjelperen
  kjører utenfor agentcontainerne; kode og private kontrollfiler monteres ikke inn.
- Én agent og én proxy vises. Hvert ekstra miljø får sitt eget par og egne
  nettverk. Docker-instansen og kontrollsiden er felles.
- Agenten har ingen forbindelse til Docker-socketen og ingen direkte
  internettrute. Pilene fra Docker viser styring, ikke en kontrollkanal agenten kan bruke.
- Proxyen leser policy og nødvendig privat CA fra skrivebeskyttede mounts;
  ekte tokens tilføres bare proxyens miljø. Kontrollhjelperen gjør navneoppløsning
  og adressevalidering før de fastlåste adressene tas i bruk.
- Prosjektmapper ligger på verten og overlever fjerning av miljøet. Agentens
  hjem ligger i containerlaget; separat profilvolum støttes ikke.
  Midlertidige miljøer fra `run` fjernes når kommandoen avsluttes.
- Rootless-containerne deler vertens kjerne. Ved et utbrudd med `agentbox`
  sine rettigheter gjelder brukerens samlede vertstilgang, også til andre registrerte prosjekter.
  Agentens UID 0 mappes til tjenestebrukeren på verten; proxyen bruker en egen
  containerbruker og får ikke prosjektmapper montert inn.

## Sekvens: fra miljøvariabel til ekte API-nøkkel

Agentbox setter en substituttverdi i agentens miljøvariabel `TOKEN`.
Substituttet er en generert plassholder. Den ekte nøkkelen fra vertens miljø
gis til proxyen, som kan bytte den inn når agenten bruker riktig header mot
et godkjent mål.

Diagrammet viser hovedflyten for en HTTPS-destinasjon med nøkkelregel.
Opprettelse av containere og TLS-forbindelser er utelatt.

![Tokenflyt: verten gir agenten en plassholder, og proxyen erstatter den mot riktig tjeneste](diagrams/agentbox-token-sequence.svg)

<details>
<summary>PlantUML-kilde</summary>

```plantuml
@startuml agentbox-token-sequence
title Agentbox - fire steg fra substitutt til ekte nøkkel
hide footbox
autonumber
skinparam sequenceMessageAlign center
participant "Agentbox" as host
participant "Agent" as agent
participant "Proxy" as proxy
participant "Godkjent API-tjeneste" as api
note over host: Leser ekte nøkkel fra vertens TOKEN.
== Klargjøring ==
host -> agent: Setter TOKEN=substitutt
host -> proxy: Konfigurerer substitutt, ekte nøkkel\nog godkjente domener og headere
== API-kall ==
agent -> proxy: Gjør API-kall med substituttet i headeren
note over proxy: Sjekker domene, header og substitutt.
proxy -> api: Erstatter substituttet med ekte nøkkel\nog sender API-kallet
@enduml
```

</details>

Agenten har en verdi den kan bruke, men den ekte nøkkelen ligger på den
betrodde siden. Uten riktig plassholder, header og destinasjon setter proxyen
ikke inn nøkkelen.

Substituttet beholdes ved stopp/start og proxybytte, også når operatøren
roterer den ekte nøkkelen. Nye variabelnavn krever eksplisitt gjenskaping av
agentcontaineren. Hvert miljø har sitt eget plassholderkart.

Ekte tokenverdier tilføres via CLI og kontrollhjelperens stdin til proxyens
miljø. Docker lagrer miljøet i metadata; full kontroll over tjenestebrukeren
og daemonen kan avsløre nøkkelen. En godkjent tjeneste kan også returnere den
i et svar. Se [oppsett og avgrensninger](usage.md#api-tokens-i-proxyen).

## Vedlikehold av diagrammene

Navngitte PlantUML-blokker i dette dokumentet er kilden til SVG- og PNG-filene
i `docs/diagrams/`. Kilden og bildene skal oppdateres sammen:

```sh
python3 scripts/render-diagrams.py
python3 scripts/render-diagrams.py --format png
```

PlantUML med lokalt C4-bibliotek og Graphviz må være installert.

```sh
python3 scripts/render-diagrams.py --jar /sti/til/plantuml-1.2026.9.jar
```

Nivåene følger C4-modellens beskrivelser av
[systemkontekst](https://c4model.com/diagrams/system-context) og
[containere](https://c4model.com/diagrams/container). Konkret oppførsel og
begrensninger beskrives i [implementasjonsvalgene](decisions.md).
