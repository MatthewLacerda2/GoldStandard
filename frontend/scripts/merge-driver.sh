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
#     worktree's own copy.
#
#   merge-driver.sh <locale|route-tree|append> %O %A %B %L %P %S %X %Y
#     What git calls. Without bun on PATH (a GUI client's trimmed PATH, say),
#     or when bun fails without writing a merge (a crash, a missing module),
#     %A would stay our side with no markers, and git would record a conflict
#     that hides theirs. This falls back to git's own line merge instead, so a
#     conflict always carries markers.
set -u

if [ "${1:-}" = install ]; then
	for spec in "locale:locale JSON, merged key by key" \
		"route-tree:TanStack routeTree.gen.ts, regenerated" \
		"append:append-only registries, both insertions kept"; do
		kind=${spec%%:*}
		git config "merge.frontend-$kind.name" "${spec#*:}"
		git config "merge.frontend-$kind.driver" \
			"sh frontend/scripts/merge-driver.sh $kind %O %A %B %L %P %S %X %Y"
	done
	exit 0
fi

here=$(dirname "$0")
if command -v bun >/dev/null 2>&1; then
	bun "$here/merge-driver.ts" "$@"
	status=$?
	# 0 is a merge; a conflict the driver itself reports leaves markers in %A.
	if [ "$status" -eq 0 ] || grep -q '^<<<<<<<' "$3"; then
		exit "$status"
	fi
	echo "merge-driver: bun exited $status without a merge; line merge of $6" >&2
else
	echo "merge-driver: bun is not on PATH; line merge of $6" >&2
fi
git merge-file --marker-size="$5" -L "${8:-ours}" -L "${7:-base}" -L "${9:-theirs}" "$3" "$2" "$4"
exit 1
