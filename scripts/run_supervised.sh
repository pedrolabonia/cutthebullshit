#!/bin/zsh
# Unattended run: keeps `cutthebullshit supervise` going until it finishes (it resumes from tmp_write/RUN NN/_supervise.json).
#   nohup caffeinate -dims scripts/run_supervised.sh <run number> <folders...> > <log> 2>&1 &
# Uses the Python that has cutthebullshit installed: $PYTHON, else python3 on the PATH.
py=${PYTHON:-python3}
run=$1; shift
n=0
until "$py" -u -m cutthebullshit supervise "$@" --run "$run"; do
  n=$((n + 1))
  if [ $n -ge 20 ]; then echo "[launcher $(date +%H:%M:%S)] supervisor failed 20 times, giving up"; exit 1; fi
  echo "[launcher $(date +%H:%M:%S)] supervisor exited with an error - restarting in 60s ($n/20)"
  sleep 60
done
echo "[launcher $(date +%H:%M:%S)] finished"
