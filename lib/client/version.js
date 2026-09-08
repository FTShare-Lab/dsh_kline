// The update channel offers stable releases only. A stable release of the same
// base version must still be offered to users running its release candidate.
export function isNewerStableVersion(candidate, current) {
    const next = /^(\d+)\.(\d+)\.(\d+)$/.exec(candidate);
    const installed = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(current);
    if (!next || !installed)
        return false;
    for (let index = 1; index <= 3; index++) {
        const difference = Number(next[index]) - Number(installed[index]);
        if (difference)
            return difference > 0;
    }
    return Boolean(installed[4]);
}
