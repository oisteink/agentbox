# Bash completion for abx. Also usable with: source <(abx completion bash)
_abx()
{
  local cur="${COMP_WORDS[COMP_CWORD]}" prev="${COMP_WORDS[COMP_CWORD-1]}"
  local action="${COMP_WORDS[1]}" operation="" choices="" kind="" value
  local i start=2 positional=0 separated=0
  COMPREPLY=()

  local -a words=("${COMP_WORDS[@]}")
  if (( COMP_CWORD > 1 )) && [[ "$action" == --json || "$action" == --yes ]]; then
    # Re-evaluate with global flags removed, preserving the active word.
    local -a filtered=("${words[0]}")
    for (( i=1; i<COMP_CWORD; i++ )); do
      [[ "${words[i]}" == --json || "${words[i]}" == --yes ]] || filtered+=("${words[i]}")
    done
    filtered+=("$cur")
    local -a COMP_WORDS=("${filtered[@]}")
    local COMP_CWORD=$((${#filtered[@]} - 1))
    _abx
    return
  fi

  if (( COMP_CWORD == 1 )); then
    choices="doctor status image validate mount proxy start run stop remove logs login-api-key exec completion --help --json --yes"
  elif [[ "$action" == image ]]; then
    if (( COMP_CWORD == 2 )); then
      choices="list new edit build inspect remove --help --json --yes"
    elif [[ "$prev" == --template ]]; then
      mapfile -t COMPREPLY < <(abx completion --names templates 2>/dev/null | while IFS= read -r value; do
        [[ "$value" == "$cur"* ]] && printf '%s\n' "$value"
      done)
      return
    elif [[ "${COMP_WORDS[2]}" == new ]]; then
      choices="--template --help --json --yes"
    elif [[ "${COMP_WORDS[2]}" != list ]]; then
      kind=images
      start=3
    fi
  elif [[ "$action" == proxy ]]; then
    if (( COMP_CWORD == 2 )); then
      choices="apply stop rotate-ca build --help --json --yes"
    elif [[ "${COMP_WORDS[2]}" == apply ]]; then
      compopt -o filenames
      mapfile -t COMPREPLY < <(compgen -f -- "$cur")
      if [[ "$cur" != */* ]]; then
        while IFS= read -r value; do
          [[ -n "$value" && "$value" == "$cur"* ]] && COMPREPLY+=("$value")
        done < <(abx completion --names configs 2>/dev/null)
      fi
      return
    elif [[ "${COMP_WORDS[2]}" != build ]]; then
      kind=environments
      start=3
    fi
  elif [[ "$prev" == --key-file ]]; then
    compopt -o filenames
    mapfile -t COMPREPLY < <(compgen -f -- "$cur")
    return
  elif [[ "$action" == start || "$action" == run || "$action" == exec || "$action" == validate ]] && [[ "$cur" != -* ]]; then
    for (( i=2; i<COMP_CWORD; i++ )); do
      case "${COMP_WORDS[i]}" in
        --keep-running|--json|--yes) ;;
        *) positional=1 ;;
      esac
    done
    if (( ! positional )); then
      compopt -o filenames
      mapfile -t COMPREPLY < <(compgen -f -- "$cur")
      if [[ "$cur" != */* ]]; then
        while IFS= read -r value; do
          [[ -n "$value" && "$value" == "$cur"* && ! -e "$value" ]] && COMPREPLY+=("$value")
        done < <(abx completion --names configs 2>/dev/null)
      fi
      return
    fi
    choices="--help --json --yes"
    [[ "$action" == start || "$action" == exec ]] && choices="--keep-running $choices"
  elif [[ "$action" == mount ]]; then
    if (( COMP_CWORD == 2 )); then
      choices="add list check revoke remove --help --json --yes"
    else
      operation="${COMP_WORDS[2]}"
      start=3
      [[ "$operation" == check || "$operation" == remove || "$operation" == revoke ]] && kind=mounts
      [[ "$operation" == check ]] && choices="--fix --help --json --yes"
      if [[ "$operation" == add ]]; then
        choices="--volume --help --json --yes"
        if (( COMP_CWORD >= 4 )) && [[ "$cur" != -* && "${COMP_WORDS[3]}" != --* ]]; then
          compopt -o filenames
          mapfile -t COMPREPLY < <(compgen -d -- "$cur")
          return
        fi
      fi
    fi
  else
    case "$action" in
      start|exec) choices="--keep-running --help --json --yes" ;;
      run|validate) choices="--help --json --yes" ;;
      stop|remove) kind=environments; choices="--help --json --yes" ;;
      logs) kind=environments; choices="--proxy --help --json --yes" ;;
      login-api-key) kind=environments; choices="--key-file --help --json --yes" ;;
      completion) choices="bash --help --json --yes" ;;
    esac
  fi

  # Skip option values when locating the environment/mount positional argument.
  for (( i=start; i<COMP_CWORD; i++ )); do
    case "${COMP_WORDS[i]}" in
      --key-file) (( i++ )) ;;
      --key-file=*|--volume|--fix|--proxy|--keep-running|-h|--help|--json|--yes) ;;
      --) separated=1; break ;;
      *) positional=1 ;;
    esac
  done
  if [[ "$action" == exec ]] && { (( separated )) || { (( positional )) && [[ -n "$cur" && "$cur" != -* ]]; }; }; then
    return
  fi
  if [[ "$cur" == -* || -z "$kind" ]] || (( positional )); then
    mapfile -t COMPREPLY < <(compgen -W "$choices" -- "$cur")
  else
    while IFS= read -r value; do
      [[ -n "$value" && "$value" == "$cur"* ]] && COMPREPLY+=("$value")
    done < <(abx completion --names "$kind" 2>/dev/null)
  fi
  return 0
}
complete -F _abx abx
