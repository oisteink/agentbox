# Utvikling av Agentbox

Kjør fra en arbeidskopi av repoet. Python 3.12 eller nyere og uv kreves.
Arbeid på egne grener og oppdater dokumentasjon før squash merge til `main`;
se [bidragsreglene](../AGENTS.md).

## Lokale kontroller

Kjør hele den lokale pakken med `scripts/check.sh`. [Teststrategien](testing.md)
beskriver hvordan tester lages, hvilket bevis de gir, og når labprøver kreves.
De enkelte kommandoene er:

```sh
uv sync --extra dev --locked
uv run --locked pytest
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
bash -n scripts/*.sh scripts/lab/*.sh src/agentbox/templates/codex/codex src/agentbox/completions/abx.bash
(cd proxy && GOTOOLCHAIN=go1.27.3 go test -race ./... && GOTOOLCHAIN=go1.27.3 go vet ./...)
(cd proxy && GOTOOLCHAIN=go1.27.3 go run golang.org/x/vuln/cmd/govulncheck@v1.9.0 ./...)
test -z "$(gofmt -l proxy/*.go)"
```

`pytest` kjører enhetstester som standard. Integrasjonstestene krever installert
kontrollverktøy, `AGENTBOX_LAB=1` og vertsnavnet `agentbox-lab`.
Go-modulen ligger i `proxy/` og krever Go 1.27.3. Docker-bygget kjører også
Go-testene, vet og govulncheck med den valgte toolchainen. BuildKit kan gjenbruke
et tidligere resultat fra cache; kjør govulncheck-kommandoen over for en ny
sjekk mot dagens database. `scripts/lab/check.sh` inne i laben installerer
aktuell kode, bygger images og kjører selvstendige livssyklusscenarier og
proxyprøver med låste testavhengigheter. Kjør labprøver
sekvensielt: de endrer felles nettverk, vertsadresser og installasjonsinnstillinger.

## Disponibel integrasjonslab

Den disponible KVM-laben krever QEMU, `qemu-img`, `xorriso`, curl og SSH.
Labkommandoene nedenfor skal kjøres utenfor en agentsandkasse som sperrer KVM:

```sh
scripts/lab/vm.sh prepare
scripts/lab/vm.sh start
scripts/lab/vm.sh ssh
scripts/lab/vm.sh stop
```

Bootstrap- og nettverksprøver har en eksplisitt `agentbox-lab`-vertskontroll.
Reproduksjon av testløpet er beskrevet i [teststatus](test-results.md).
Koden kopieres inn med tar/SSH; vertens mapper deles ikke inn i VM-en.

## Avinstallasjonsprøve

Denne prøven sletter Agentbox-installasjonen i VM-en, og må kjøres sist.
Den krever eksplisitt `AGENTBOX_UNINSTALL_LAB=1` og vertsnavnet `agentbox-lab`.
Labinngangen installerer og bygger aktuell kilde, starter rootful Docker som
kontrollinstans og kjører avinstallasjon etter livssyklus- og proxyprøvene:

```sh
scripts/lab/vm.sh ssh 'cd /home/developer/agentbox-src && bash scripts/lab/check.sh --uninstall'
```

Skriptet bruker midlertidige prosjekter og avinstallerer fra repoet med
`sudo scripts/uninstall.sh`. Det finnes ingen avinstallasjonskommando i CLI-en.
