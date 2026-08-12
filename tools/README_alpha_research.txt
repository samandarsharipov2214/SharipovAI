Alpha Candidate v1 command flow (research only)

1. Build a canonical public Bybit Spot dataset outside Git:
   python tools/import_bybit_spot_history.py --output-dir <dir> --dataset-id <id> --dataset-version <v> --start <iso> --end <iso>

2. Freeze the experiment before final OOS:
   python tools/preregister_alpha_experiment.py --manifest <dir>/manifest.json --output <experiment.json> --experiment-id <id> --train <start,end> --validation <start,end> --validation <start,end> --final-oos <start,end>

3. Run the exact preregistered experiment once:
   python tools/run_preregistered_alpha_experiment.py --manifest <dir>/manifest.json --experiment <experiment.json> --report <result.json>

The commands never enable Paper, Testnet or Mainnet. A real result does not exist until step 3 is executed against a final-OOS-eligible real dataset.
