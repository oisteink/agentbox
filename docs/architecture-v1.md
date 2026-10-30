# Arkitektur for første versjon

Første versjon skal kjøre agentmiljøer i en egen rootless Docker-instans,
med eksplisitt tilgang til prosjektmapper og utgående trafikk via proxy.
Dette er vedtatt design. Se [implementasjonsvalg](decisions-mvp.md) og
[teststatus](test-results.md) for implementasjonens presiseringer og verifikasjon.

## Eierskap og kontroll

- En egen Linux-bruker, `agentbox`, eier daemon, socket, images og volumer.
- Brukeren skal ha `/var/lib/agentbox` som hjemmekatalog på verten, med
  Docker-data og konfigurasjon adskilt fra personlige hjemmekataloger.
  Denne katalogen skal ikke monteres inn i agentcontainerne. Containerens
  hjemmekatalog er `/home/agent` og ligger i containerens eget filsystem.
- Oppstart skal eksplisitt velge prosjektets Docker-instans.
- Docker-socketen skal ikke monteres i agentcontainerne.
- Kontrollverktøyet kjører utenfor agentmiljøene. En fast administratorinstallert
  hjelper kjøres som `agentbox` gjennom en avgrenset sudo-regel.

## Tilgang til prosjektmapper

Prosjekter skal kunne velges og byttes uten å flyttes. Flere arbeidsmiljøer
skal kunne kjøre samtidig, og ett miljø kan få flere eksplisitte mounts.
MVP-en skal montere eksisterende prosjektmapper direkte. Endringer i koden
skal være synlige både på verten og i containeren.

ACL-er skal gi `agentbox` traversering av nødvendige foreldrekataloger og
lese- og skrivetilgang til valgte arbeidsmapper. Foreldrekatalogene trenger
ikke listetilgang. Symbolske lenker gir ikke ekstra rettigheter.

Eksempel på mounts:

| På verten | I containeren |
| --- | --- |
| `/home/ok/src/pacman` | `/home/agent/src/pacman` |
| `/home/ok/project/pub-pc` | `/home/agent/project/pub-pc` |

Agenten skal som utgangspunkt kjøre som UID 0 i den rootlesse containeren,
som mappes til `agentbox` på verten. Nye filer vil normalt eies av
`agentbox`. ACL-er på eksisterende filer og standard-ACL-er på kataloger
skal sikre at både den personlige brukeren og `agentbox` kan arbeide videre.
Modusendringer og filutskifting må testes med aktuelle utviklingsverktøy.

## Nettverk og images

Hvert arbeidsmiljø skal ha eget lukket nettverk. En Squid-proxy eller
tilsvarende kobles til dette og et eksternt nettverk. Bare eksplisitt tillatte
destinasjoner og porter skal kunne nås. Proxyoppsett i miljøvariabler skal
støttes av nettverksregler som blokkerer direkte utgående forbindelser.

Start med ett agentimage. Image og oppstartskommando skal kunne velges
uavhengig av nettverks-, ACL- og monteringslogikken.

## Sikkerhetsgrense og verifikasjon

Mountene avgrenser hvilke vertsmapper agenten ser i normal containerkjøring.
Ved et utbrudd som gir daemonbrukerens rettigheter, gjelder alle rettighetene
til `agentbox`, inkludert andre delte prosjekter og filer som allerede er
tilgjengelige for lokale brukere. Felles daemonbruker gir ikke separat
vertsisolering mellom prosjektene.

Før første versjon godkjennes, skal vi verifisere:

- Tillatt proxytrafikk fungerer; andre destinasjoner og direkte trafikk blokkeres.
- Proxyfeil åpner ingen alternativ vei ut.
- DNS, IPv6, vertsadresser og private destinasjoner ikke omgår policyen.
- Bare valgte mapper vises, og begge brukerne kan redigere nye filer.
- To arbeidsmiljøer kan kjøre samtidig med ulike mounts og images.
- Ressursgrenser håndheves av vertens cgroup-oppsett.

## Videre arbeid etter MVP

Worktree-støtte er utenfor MVP-en. Senere skal vi vurdere hvordan linked
worktrees kan brukes, inkludert tilgang til Git-metadata utenfor arbeidsmappen.

Når MVP-en fungerer, skal den sammenlignes med OpenShell og Docker Sandboxes.
Sammenligningen skal bygge på vår testede løsning og undersøkelser av
alternativenes faktiske egenskaper. Vurder særlig:

- Isoleringsgrenser, vertsrettigheter og nettverkspolicy.
- Direkte montering av eksisterende prosjekter og filrettigheter.
- Prosjektbytte, samtidige arbeidsmiljøer og støtte for ulike images.
- Oppsett, daglig bruk, vedlikehold og plattformkrav.

## Teknisk grunnlag

- [Rootless UID-mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/)
- [Docker gateway-moduser](https://docs.docker.com/engine/network/port-publishing/#gateway-modes)
- [Squid CONNECT og HTTPS](https://wiki.squid-cache.org/Features/HTTPS)
- [Git worktrees](https://git-scm.com/docs/git-worktree)
