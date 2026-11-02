"""The geometry side of the viewer. Everything here runs inside a worker process (one per open
document), so a file that crashes OpenCASCADE takes down only its own worker, never the window."""
