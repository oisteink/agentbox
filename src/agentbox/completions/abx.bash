# Bash completion for abx. Also usable with: source <(abx completion bash)
_abx()
{
  local cur="${COMP_WORDS[COMP_CWORD]}" prev="${COMP_WORDS[COMP_CWORD-1]}"
  local action="${COMP_WORDS[1]}" operation="" choices="" kind="" value
  local i start=2 positional=0
  COMPREPLY=()

  if (( COMP_CWORD == 1 )); then
    choices="doctor status image validate project proxy start run stop remove shell logs login-api-key exec completion --help"
  elif [[ "$action" == image ]]; then
    if (( COMP_CWORD == 2 )); then
      choices="ls new edit build inspect rm --help"
    elif [[ "$prev" == --template ]]; then
      choices="base codex opencode claude-code"
    elif [[ "${COMP_WORDS[2]}" == new ]]; then
      choices="--template --help"
    elif [[ "${COMP_WORDS[2]}" != ls ]]; then
      kind=images
      start=3
    fi
  elif [[ "$action" == proxy ]]; then
    if (( COMP_CWORD == 2 )); then
      choices="apply stop rotate-ca build --help"
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
  elif [[ "$prev" == --key-file ]] || { [[ "$action" == start || "$action" == run || "$action" == validate ]] && (( COMP_CWORD == 2 )) && [[ "$cur" != -* ]]; }; then
    compopt -o filenames
    mapfile -t COMPREPLY < <(compgen -f -- "$cur")
    if [[ "$action" == start || "$action" == run || "$action" == validate ]] && [[ "$prev" != --key-file && "$cur" != */* ]]; then
      while IFS= read -r value; do
        [[ -n "$value" && "$value" == "$cur"* && ! -e "$value" ]] && COMPREPLY+=("$value")
      done < <(abx completion --names configs 2>/dev/null)
    fi
    return
  elif [[ "$prev" == --path ]]; then
    compopt -o filenames
    mapfile -t COMPREPLY < <(compgen -d -- "$cur")
    return
  elif [[ "$action" == project ]]; then
    if (( COMP_CWORD == 2 )); then
      choices="add list check repair revoke --help"
    else
      operation="${COMP_WORDS[2]}"
      start=3
      [[ "$operation" == check || "$operation" == repair || "$operation" == revoke ]] && kind=projects
      [[ "$operation" == add ]] && choices="--path --help"
    fi
  else
    case "$action" in
      start|run|validate) choices="--help" ;;
      stop|remove|shell|exec) kind=environments; choices="--help" ;;
      logs) kind=environments; choices="--proxy --help" ;;
      login-api-key) kind=environments; choices="--key-file --help" ;;
      completion) choices="bash --help" ;;
    esac
  fi

  # Skip option values when locating the environment/project positional argument.
  for (( i=start; i<COMP_CWORD; i++ )); do
    case "${COMP_WORDS[i]}" in
      --key-file|--path) (( i++ )) ;;
      --key-file=*|--path=*|--proxy|-h|--help) ;;
      --) break ;;
      *) positional=1 ;;
    esac
  done
  if [[ "$action" == exec ]] && (( positional )); then
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
