#!/bin/sh
# The git merge drivers for the locale JSON, routeTree.gen.ts and the
# house-rule registries. The logic is in merge-driver.ts; this shell is what
# git runs, for two reasons:
#
#   merge-driver.sh install
#     Registers the drivers in this clone's git config. `.gitattributes`
#     names them, but git only runs a driver its config defines, and config is
#     per clone (worktrees share it), so `make setup` runs this. Git runs a
#     driver from the top of the worktree, so the relative path below is each
#     worktree's own copy. Where that copy is missing (a sparse checkout, a
#     branch that moved it), the registered command runs git's line merge.
#
#   merge-driver.sh <locale|route-tree|append> %O %A %B %L %P %S %X %Y
#     What git calls. Without bun on PATH (a GUI client's trimmed PATH, say),
#     or when bun fails without writing a merge (a crash, a missing module),
#     %A would stay our side with no markers, and git would record a conflict
#     that hides theirs. This falls back to git's own line merge instead, so a
#     conflict always carries markers.
#
# The exit contract, git's: 0 is a clean merge in %A, 1 a conflict written
# into %A with markers. merge-driver.ts says which with 0 and CONFLICT (3, so
# a crash's 1 is never taken for it); any other status is a run that wrote
# nothing, and the line merge decides.
set -u
CONFLICT=3

if [ "${1:-}" = install ]; then
	script=frontend/scripts/merge-driver.sh
	line_merge="git merge-file --marker-size=%L -L %X -L %S -L %Y %A %O %B"
	for spec in "locale:locale JSON, merged key by key" \
		"route-tree:TanStack routeTree.gen.ts, regenerated" \
		"append:append-only registries, both insertions kept"; do
		kind=${spec%%:*}
		git config "merge.frontend-$kind.name" "${spec#*:}"
		git config "merge.frontend-$kind.driver" "if [ -f $script ]; then \
sh $script $kind %O %A %B %L %P %S %X %Y; else \
echo 'merge-driver: $script is missing; line merge' >&2; $line_merge; fi"
	done
	exit 0
fi

# %S %X %Y are git's own labels for the sides; an older git leaves them unexpanded.
label() {
	case "$1" in
	'' | %*) echo "$2" ;;
	*) echo "$1" ;;
	esac
}

here=$(dirname "$0")
if command -v bun >/dev/null 2>&1; then
	# --no-install: without frontend/node_modules, bun would otherwise fetch
	# packages (any version, maybe over the network) instead of failing.
	bun --no-install "$here/merge-driver.ts" "$@"
	status=$?
	[ "$status" -eq 0 ] && exit 0
	[ "$status" -eq "$CONFLICT" ] && exit 1
	echo "merge-driver: bun exited $status without a merge; line merge of $6" >&2
else
	echo "merge-driver: bun is not on PATH; line merge of $6" >&2
fi
git merge-file --marker-size="$5" \
	-L "$(label "${8:-}" ours)" -L "$(label "${7:-}" base)" -L "$(label "${9:-}" theirs)" \
	"$3" "$2" "$4"
[ $? -eq 0 ] && exit 0
exit 1
