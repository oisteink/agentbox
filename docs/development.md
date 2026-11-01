# Utvikling av Agentbox

Kjør fra en arbeidskopi av repoet. Python 3.12 eller nyere og uv kreves.
Arbeid på egne grener og oppdater dokumentasjon før squash merge til `main`;
se [bidragsreglene](../AGENTS.md).

## Lokale kontroller

```sh
uv sync --extra dev --locked
uv run --locked pytest
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
bash -n scripts/*.sh scripts/lab/*.sh images/dev/codex src/agentbox/completions/agentbox.bash
(cd proxy && go test -race ./... && go vet ./...)
(cd proxy && GOTOOLCHAIN=go1.27.3 go run golang.org/x/vuln/cmd/govulncheck@v1.9.0 ./...)
test -z "$(gofmt -l proxy/*.go)"
```

`pytest` kjører enhetstester som standard. Integrasjonstesten krever installert
kontrollverktøy, `AGENTBOX_LAB=1` og vertsnavnet `agentbox-lab`.
Go-modulen ligger i `proxy/` og krever Go 1.27.3. Docker-bygget kjører også
Go-testene, vet og govulncheck med den valgte toolchainen. BuildKit kan gjenbruke
et tidligere resultat fra cache; kjør govulncheck-kommandoen over for en ny
sjekk mot dagens database. For CLI-/proxyprøver med syntetiske tokens brukes
`sudo python3 scripts/lab/credential_proxy.py` inne i laben. Kjør labprøver
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
Labimagene må være bygget og rootful Docker startet som kontrollinstans:

```sh
scripts/lab/vm.sh ssh 'sudo systemctl start docker'
scripts/lab/vm.sh ssh 'cd /home/developer/agentbox-src && AGENTBOX_UNINSTALL_LAB=1 python3 -m pytest -q tests/integration/test_uninstall.py'
```

Skriptet bruker midlertidige prosjekter og avinstallerer fra repoet med
`sudo scripts/uninstall.sh`. Det finnes ingen avinstallasjonskommando i CLI-en.
