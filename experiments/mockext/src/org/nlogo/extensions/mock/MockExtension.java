package org.nlogo.extensions.mock;

import org.nlogo.api.Argument;
import org.nlogo.api.Command;
import org.nlogo.api.Context;
import org.nlogo.api.DefaultClassManager;
import org.nlogo.api.ExtensionException;
import org.nlogo.api.ExtensionManager;
import org.nlogo.api.PrimitiveManager;
import org.nlogo.api.Reporter;
import org.nlogo.core.Syntax;
import org.nlogo.core.SyntaxJ;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

// Mock external-call extension for experiments 2 and 3.
// mock:block ms    - blocks the engine thread, SWALLOWING interrupts (simulates uninterruptible I/O)
// mock:sleep ms    - blocks the engine thread, converting interrupt into ExtensionException
// mock:yield ms    - LevelSpace UnlockAndBlock pattern: background work + world.wait(1) polling loop
// mock:start-injectors n / mock:stop-injectors / mock:fetch / mock:injected  - experiment 3 queue
public class MockExtension extends DefaultClassManager {

  static final ConcurrentLinkedQueue<Long> QUEUE = new ConcurrentLinkedQueue<>();
  static final AtomicLong INJECTED = new AtomicLong();
  static final AtomicBoolean RUNNING = new AtomicBoolean(false);
  static final List<Thread> INJECTORS = new ArrayList<>();
  static final int SOFT_CAP = 500_000;

  @Override
  public void load(PrimitiveManager pm) {
    pm.addPrimitive("block", new Block());
    pm.addPrimitive("sleep", new Sleep());
    pm.addPrimitive("yield", new Yield());
    pm.addPrimitive("start-injectors", new StartInjectors());
    pm.addPrimitive("stop-injectors", new StopInjectors());
    pm.addPrimitive("fetch", new Fetch());
    pm.addPrimitive("injected", new Injected());
  }

  @Override
  public void unload(ExtensionManager em) {
    stopAll();
  }

  static void stopAll() {
    RUNNING.set(false);
    synchronized (INJECTORS) {
      for (Thread t : INJECTORS) { t.interrupt(); }
      INJECTORS.clear();
    }
  }

  public static class Block implements Command {
    @Override public Syntax getSyntax() {
      return SyntaxJ.commandSyntax(new int[] { Syntax.NumberType() });
    }
    @Override public void perform(Argument[] args, Context ctx) throws ExtensionException {
      long ms = (long) args[0].getDoubleValue();
      long end = System.nanoTime() + ms * 1_000_000L;
      while (System.nanoTime() < end) {
        try { Thread.sleep(5); }
        catch (InterruptedException e) { /* deliberately swallowed: simulates uninterruptible I/O */ }
      }
    }
  }

  public static class Sleep implements Command {
    @Override public Syntax getSyntax() {
      return SyntaxJ.commandSyntax(new int[] { Syntax.NumberType() });
    }
    @Override public void perform(Argument[] args, Context ctx) throws ExtensionException {
      long ms = (long) args[0].getDoubleValue();
      try { Thread.sleep(ms); }
      catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        throw new ExtensionException("mock:sleep interrupted (halt)");
      }
    }
  }

  public static class Yield implements Command {
    @Override public Syntax getSyntax() {
      return SyntaxJ.commandSyntax(new int[] { Syntax.NumberType() });
    }
    @Override public void perform(Argument[] args, Context ctx) throws ExtensionException {
      long ms = (long) args[0].getDoubleValue();
      Object worldLock = ctx.world();
      final AtomicBoolean done = new AtomicBoolean(false);
      Thread worker = new Thread(() -> {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) {}
        done.set(true);
        synchronized (worldLock) { worldLock.notifyAll(); }
      }, "mock-yield-worker");
      worker.setDaemon(true);
      worker.start();
      // LevelSpace UnlockAndBlock pattern: release the World lock while waiting
      while (!done.get()) {
        synchronized (worldLock) {
          try { worldLock.wait(1); }
          catch (InterruptedException e) {
            worker.interrupt();
            Thread.currentThread().interrupt();
            throw new ExtensionException("mock:yield interrupted (halt)");
          }
        }
      }
    }
  }

  public static class StartInjectors implements Command {
    @Override public Syntax getSyntax() {
      return SyntaxJ.commandSyntax(new int[] { Syntax.NumberType() });
    }
    @Override public void perform(Argument[] args, Context ctx) throws ExtensionException {
      stopAll();
      QUEUE.clear();
      INJECTED.set(0);
      RUNNING.set(true);
      int n = (int) args[0].getDoubleValue();
      synchronized (INJECTORS) {
        for (int i = 0; i < n; i++) {
          Thread t = new Thread(() -> {
            while (RUNNING.get() && !Thread.currentThread().isInterrupted()) {
              if (QUEUE.size() < SOFT_CAP) {
                QUEUE.offer(INJECTED.incrementAndGet());
              } else {
                try { Thread.sleep(1); } catch (InterruptedException e) { return; }
              }
            }
          }, "mock-injector");
          t.setDaemon(true);
          t.start();
          INJECTORS.add(t);
        }
      }
    }
  }

  public static class StopInjectors implements Command {
    @Override public Syntax getSyntax() { return SyntaxJ.commandSyntax(new int[] {}); }
    @Override public void perform(Argument[] args, Context ctx) { stopAll(); }
  }

  public static class Fetch implements Reporter {
    @Override public Syntax getSyntax() {
      return SyntaxJ.reporterSyntax(new int[] {}, Syntax.NumberType());
    }
    @Override public Object report(Argument[] args, Context ctx) {
      Long v = QUEUE.poll();
      return v == null ? Double.valueOf(-1) : Double.valueOf(v.doubleValue());
    }
  }

  public static class Injected implements Reporter {
    @Override public Syntax getSyntax() {
      return SyntaxJ.reporterSyntax(new int[] {}, Syntax.NumberType());
    }
    @Override public Object report(Argument[] args, Context ctx) {
      return Double.valueOf(INJECTED.get());
    }
  }
}
