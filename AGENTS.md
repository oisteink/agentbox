# Repository Guidelines

## Formål og arkitektur

Prosjektet skal tilby Docker-isolering for kodeagenter. Kjør miljøet på en egen rootless Docker-instans. Agentcontainere skal ligge på et lukket nettverk uten direkte internettilgang.

En Squid-proxy eller tilsvarende skal koble det lukkede nettverket til et eksternt nettverk. Utgående tilgang skal styres av en eksplisitt liste over tillatte adresser; øvrig trafikk skal avvises. Agentcontainere skal ikke kobles direkte til det eksterne nettverket.

Worktrees og andre arbeidsmapper skal kunne monteres inn. Løsningen kan starte med ett agentimage, men konfigurasjonen skal støtte flere imagetyper uten endringer i isoleringsmekanismen.

## Prosjektstruktur

Repoet har foreløpig ingen implementasjon, tester eller byggesystem. Bruk følgende struktur når delene opprettes:

- `images/<navn>/`: Dockerfiles og imagespesifikke ressurser.
- `proxy/`: proxykonfigurasjon og regler for tillatte adresser.
- `scripts/`: oppsett, oppstart og vedlikehold.
- `tests/`: integrasjonstester for isolering og tilgang.
- `docs/`: arkitektur, konfigurasjon og brukseksempler.

Hold felles nettverks- og monteringslogikk adskilt fra imagespesifikke valg.

## Bygging, testing og utvikling

Ingen bygge-, oppstarts- eller testkommandoer er etablert ennå. Dokumenter konkrete kommandoer når implementasjonen kommer. Kommandoene skal eksplisitt velge prosjektets rootless-instans, eksempelvis med `docker --context <prosjektkontekst> ...`.

## Kodestil og navngivning

Bruk to mellomrom i YAML, beskrivende filnavn og små bokstaver med bindestrek for images og tjenester. Shellskript skal bruke Bash og eksplisitt feilhåndtering. Innfør formattering og linting sammen med relevante språk; ingen slike verktøy er konfigurert nå.

## Testing og sikkerhet

Test at tillatte adresser nås via proxy, og at andre adresser og direkte internettilgang blokkeres. Verifiser rootless-kjøring, monteringsrettigheter og bruk av flere imagetyper. Testene skal feile dersom isoleringen omgås. Testrammeverk og dekningskrav er foreløpig ikke valgt.

Monter bare nødvendige mapper, helst skrivebeskyttet når mulig. Unngå privilegerte containere, vertsnettverk og montering av Docker-socketen i agentcontainere. Ikke sjekk inn hemmeligheter.

## Commits og pull requests

Repoet har ingen commithistorikk eller etablert meldingskonvensjon. Bruk korte, handlingsorienterte commitmeldinger. Pull requests skal beskrive formål, konfigurasjonsendringer og utførte tester. Forklar konsekvenser for isolering, proxyregler og monteringer når disse berøres.
