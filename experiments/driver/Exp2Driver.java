import org.nlogo.headless.HeadlessWorkspace;

// Experiment 2: synchronous extension boundary.
// Starts a blocking primitive on the engine (job) thread via command(),
// then concurrently (a) probes how long an outside thread needs to acquire
// the World lock (a stand-in for the GUI view/monitor thread) and (b) calls
// halt() and measures how long cancellation takes.
public class Exp2Driver {
  public static void main(String[] argv) throws Exception {
    String model = argv[0];
    String cmd = argv[1];
    long haltAfterMs = Long.parseLong(argv[2]);

    HeadlessWorkspace ws = HeadlessWorkspace.newInstance();
    ws.open(model, false);

    final long[] cmdDone = {0};
    final Throwable[] err = {null};
    final long t0 = System.nanoTime();
    Thread runner = new Thread(() -> {
      try { ws.command(cmd); } catch (Throwable t) { err[0] = t; }
      cmdDone[0] = System.nanoTime();
    }, "runner");
    runner.start();

    Thread.sleep(haltAfterMs);

    final long[] lockWaitMs = {-1};
    Thread lockProbe = new Thread(() -> {
      long l0 = System.nanoTime();
      synchronized (ws.world()) {
        lockWaitMs[0] = (System.nanoTime() - l0) / 1_000_000;
      }
    }, "lock-probe");
    lockProbe.start();

    long h0 = System.nanoTime();
    ws.halt();
    long haltMs = (System.nanoTime() - h0) / 1_000_000;

    lockProbe.join(30_000);
    runner.join(30_000);
    long totalMs = (cmdDone[0] == 0 ? -1 : (cmdDone[0] - t0) / 1_000_000);
    System.out.println("RESULT cmd=[" + cmd + "] worldLockWaitMs=" + lockWaitMs[0]
        + " haltReturnMs=" + haltMs + " cmdTotalMs=" + totalMs
        + " cmdOutcome=" + (err[0] == null ? "returned-normally"
                            : err[0].getClass().getSimpleName() + ": " + err[0].getMessage()));
    System.exit(0);
  }
}
