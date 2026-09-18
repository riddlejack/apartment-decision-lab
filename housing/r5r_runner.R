#!/usr/bin/env Rscript

# Thin local engine boundary for housing.routing. Python owns validation,
# caching, allowed-mode policy, and ranking; this process only asks R5 for
# genuine OSM/GTFS travel times.

args <- commandArgs(trailingOnly = TRUE)

arg_value <- function(flag, default = NULL) {
  index <- match(flag, args)
  if (is.na(index) || index == length(args)) return(default)
  args[[index + 1L]]
}

required <- function(flag) {
  value <- arg_value(flag)
  if (is.null(value) || !nzchar(value)) stop("Missing required argument: ", flag)
  value
}

memory_gb <- as.integer(required("--memory-gb"))
options(java.parameters = sprintf("-Xmx%dG", memory_gb))

suppressPackageStartupMessages({
  library(data.table)
  library(r5r)
})

network_dir <- required("--network-dir")
origins_path <- required("--origins")
destinations_path <- required("--destinations")
jobs_path <- required("--jobs")
output_path <- required("--output")
metadata_path <- required("--metadata")
timezone <- required("--timezone")
threads <- as.integer(required("--threads"))
time_window <- as.integer(required("--time-window"))
percentile <- as.integer(required("--percentile"))
max_trip <- as.integer(required("--max-trip"))
max_walk <- as.integer(required("--max-walk"))
walk_speed <- as.numeric(required("--walk-speed"))
bike_speed <- as.numeric(required("--bike-speed"))
max_lts <- as.integer(required("--max-lts"))

origins <- fread(origins_path, colClasses = c(id = "character"))
destinations <- fread(destinations_path, colClasses = c(id = "character"))
jobs <- fread(jobs_path, colClasses = "character")

r5 <- build_network(network_dir, verbose = FALSE)
on.exit(stop_r5(r5), add = TRUE)

metadata <- data.table(
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  r5r_version = as.character(packageVersion("r5r")),
  java_version = rJava::.jcall("java/lang/System", "S", "getProperty", "java.version"),
  threads = threads,
  max_memory_gb = memory_gb
)
fwrite(metadata, metadata_path)

if (file.exists(output_path)) unlink(output_path)
wrote_header <- FALSE

for (index in seq_len(nrow(jobs))) {
  job <- jobs[index]
  destination_keys <- strsplit(job$destination_keys, ";", fixed = TRUE)[[1L]]
  if (job$direction == "outbound") {
    from_points <- origins
    to_points <- destinations[id %in% destination_keys]
  } else if (job$direction == "return") {
    from_points <- destinations[id %in% destination_keys]
    to_points <- origins
  } else {
    stop("Unknown direction: ", job$direction)
  }
  if (!nrow(from_points) || !nrow(to_points)) next

  r5_mode <- switch(
    job$mode,
    walk = "WALK",
    bike = "BICYCLE",
    drive = "CAR",
    transit = c("WALK", "TRANSIT"),
    stop("Unknown mode: ", job$mode)
  )
  departure <- as.POSIXct(job$departure, format = "%Y-%m-%d %H:%M:%S", tz = timezone)
  window <- if (job$mode == "transit") time_window else 1L
  # max_walk_time constrains walk-only trips too.  Use max_trip for direct
  # walking so the configured access/transfer cap applies only to transit.
  walk_limit <- if (job$mode == "transit") max_walk else max_trip
  matrix <- travel_time_matrix(
    r5,
    origins = from_points,
    destinations = to_points,
    mode = r5_mode,
    departure_datetime = departure,
    time_window = window,
    percentiles = percentile,
    max_walk_time = walk_limit,
    max_trip_duration = max_trip,
    walk_speed = walk_speed,
    bike_speed = bike_speed,
    max_lts = max_lts,
    n_threads = threads,
    verbose = FALSE,
    progress = FALSE
  )
  if (!nrow(matrix)) next
  minutes_column <- sprintf("travel_time_p%d", percentile)
  if (!(minutes_column %in% names(matrix))) {
    stop("Expected r5r output column missing: ", minutes_column)
  }
  normalized <- matrix[, .(
    job_id = job$job_id,
    direction = job$direction,
    mode = job$mode,
    from_id = as.character(from_id),
    to_id = as.character(to_id),
    minutes = get(minutes_column)
  )]
  fwrite(normalized, output_path, append = wrote_header, col.names = !wrote_header)
  wrote_header <- TRUE
}

message(sprintf("Completed %d bounded R5 job(s)", nrow(jobs)))
