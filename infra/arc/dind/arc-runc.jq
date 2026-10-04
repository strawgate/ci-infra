# A container's OCI spec, given the runner pod's CPU quota ($quota per $period):
# one that sets no CPU quota of its own gets the pod's, so the runtimes that read
# their cgroup's cpu.max (Go 1.25+, Java, Node, .NET) count the pod's CPUs, not
# the node's 56; and its CPU count (the quota, rounded up) as GOMAXPROCS (older
# Go reads no cgroup) and PYTHON_CPU_COUNT (os.cpu_count reads none), unless
# its environment sets them.
(if (.linux.resources.cpu.quota // 0) > 0 then .
 else .linux.resources.cpu.quota = $quota | .linux.resources.cpu.period = $period end)
| (.linux.resources.cpu | ((.quota + (.period // 100000) - 1) / (.period // 100000) | floor)) as $cpus
| reduce ("GOMAXPROCS", "PYTHON_CPU_COUNT") as $name (.;
    if any(.process.env[]?; startswith($name + "=")) then .
    else .process.env += ["\($name)=\($cpus)"] end)
