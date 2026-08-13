using System.Diagnostics;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace LinguaRelay.AudioCapture;

internal static class Program
{
    private const int SampleRate = 48_000;
    private const int Channels = 2;
    private const int BitsPerSample = 16;

    public static async Task<int> Main(string[] args)
    {
        try
        {
            var processId = ParseProcessId(args);
            if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 19041))
            {
                throw new PlatformNotSupportedException(
                    "Process loopback requires Windows 10 version 2004 (build 19041) or newer."
                );
            }

            using var target = Process.GetProcessById(processId);
            await CaptureAsync((uint)processId, target);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"{error.GetType().Name}: {error.Message}");
            return 1;
        }
    }

    private static int ParseProcessId(string[] args)
    {
        if (args.Length != 2 || args[0] != "--process-id" || !int.TryParse(args[1], out var pid))
        {
            throw new ArgumentException("Usage: LinguaRelay.AudioCapture.exe --process-id <PID>");
        }
        if (pid <= 0 || pid == Environment.ProcessId)
        {
            throw new ArgumentOutOfRangeException(nameof(args), "Target PID must be another process.");
        }
        return pid;
    }

    private static async Task CaptureAsync(uint processId, Process target)
    {
        var format = new WaveFormat(SampleRate, BitsPerSample, Channels);
        await using var recorder = await new WasapiRecorderBuilder()
            .WithFormat(format)
            .WithBufferLength(20)
            .WithMmcssThreadPriority("Pro Audio")
            .WithProcessLoopback(processId, ProcessLoopbackMode.IncludeTargetProcessTree)
            .BuildAsync();

        var output = Console.OpenStandardOutput();
        var outputLock = new object();
        var stopped = new TaskCompletionSource<Exception?>(
            TaskCreationOptions.RunContinuationsAsynchronously
        );
        recorder.DataAvailable += (buffer, _, _, _) =>
        {
            lock (outputLock)
            {
                output.Write(buffer);
            }
        };
        recorder.RecordingStopped += (_, eventArgs) => stopped.TrySetResult(eventArgs.Exception);

        recorder.StartRecording();
        while (!target.HasExited && !stopped.Task.IsCompleted)
        {
            await Task.Delay(250);
            target.Refresh();
        }
        if (!stopped.Task.IsCompleted)
        {
            recorder.StopRecording();
        }
        var captureError = await stopped.Task.WaitAsync(TimeSpan.FromSeconds(5));
        lock (outputLock)
        {
            output.Flush();
        }
        if (captureError is not null)
        {
            throw new InvalidOperationException("WASAPI process capture stopped unexpectedly.", captureError);
        }
    }
}
