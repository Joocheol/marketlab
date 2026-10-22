import org.nlogo.headless.HeadlessWorkspace;

// Experiment 3: polling throughput through the single engine thread.
// N external threads inject orders into a concurrent queue; the model polls
// them out with mock:fetch. Measures orders/sec consumed for N = 1, 10, 100.
public class Exp3Driver {
  public static void main(String[] argv) throws Exception {
    String model = argv[0];
    int target = Integer.parseInt(argv[1]);

    HeadlessWorkspace ws = HeadlessWorkspace.newInstance();
    ws.open(model, false);

    long b0 = System.nanoTime();
    ws.command("repeat " + target + " [ ]");
    System.out.println("baseline: empty repeat x" + target + " = "
        + (System.nanoTime() - b0) / 1_000_000 + " ms");

    long c0 = System.nanoTime();
    ws.command("set fetched 0 while [ fetched < " + target + " ] [ set fetched fetched + 1 ]");
    System.out.println("baseline: while+set counter x" + target + " = "
        + (System.nanoTime() - c0) / 1_000_000 + " ms");

    for (int n : new int[]{1, 10, 100}) {
      ws.command("mock:start-injectors " + n);
      Thread.sleep(300); // let the queue pre-fill
      long t0 = System.nanoTime();
      ws.command("set fetched 0 while [ fetched < " + target
          + " ] [ if mock:fetch >= 0 [ set fetched fetched + 1 ] ]");
      long ms = Math.max((System.nanoTime() - t0) / 1_000_000, 1);
      ws.command("mock:stop-injectors");
      System.out.println("injectors=" + n + ": consumed " + target + " orders in " + ms
          + " ms -> " + (target * 1000L / ms) + " orders/sec");
    }
    System.exit(0);
  }
}
