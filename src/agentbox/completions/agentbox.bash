# Bash completion for agentbox. Also usable with: source <(agentbox completion bash)
_agentbox()
{
  local cur="${COMP_WORDS[COMP_CWORD]}" prev="${COMP_WORDS[COMP_CWORD-1]}"
  local action="${COMP_WORDS[1]}" operation="" choices="" kind="" value
  local i start=2 positional=0
  COMPREPLY=()

  if (( COMP_CWORD == 1 )); then
    choices="doctor status build-images pull-image validate project start stop remove shell logs login-api-key exec completion --help"
  elif [[ "$prev" == --config || "$prev" == --key-file || "$action" == validate ]]; then
    compopt -o filenames
    mapfile -t COMPREPLY < <(compgen -f -- "$cur")
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
      start) kind=environments; choices="--config --help" ;;
      stop|remove|shell|exec) kind=environments; choices="--help" ;;
      logs) kind=environments; choices="--proxy --help" ;;
      login-api-key) kind=environments; choices="--key-file --help" ;;
      completion) choices="bash --help" ;;
    esac
  fi

  # Skip option values when locating the environment/project positional argument.
  for (( i=start; i<COMP_CWORD; i++ )); do
    case "${COMP_WORDS[i]}" in
      --config|--key-file|--path) (( i++ )) ;;
      --config=*|--key-file=*|--path=*|--proxy|-h|--help) ;;
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
    done < <(agentbox completion --names "$kind" 2>/dev/null)
  fi
  return 0
}
complete -F _agentbox agentbox
