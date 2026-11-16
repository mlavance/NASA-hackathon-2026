# Local RStudio packages: install.packages(c("httr2", "ggplot2", "askpass", "gifski"))
library(httr2)
library(ggplot2)

preview_only <- FALSE

read_coordinate <- function(label, lower, upper) {
  repeat {
    value <- suppressWarnings(as.numeric(trimws(readline(paste0(label, ": ")))))
    if (is.finite(value) && value >= lower && value <= upper) return(value)
    message("Enter a number between ", lower, " and ", upper, ".")
  }
}

build_forecast <- function(preview_only) {
  from_website <- identical(Sys.getenv("WEATHER_WEB"), "1")
  username <- trimws(Sys.getenv("METEOMATICS_USER"))
  password <- Sys.getenv("METEOMATICS_PASSWORD")

  if (!from_website && interactive()) {
    if (!nzchar(username)) username <- askpass::askpass("Enter your Meteomatics username")
    if (!nzchar(password)) password <- askpass::askpass("Enter your Meteomatics password")
  }
  if (is.null(username) || !nzchar(trimws(username)) ||
      is.null(password) || !nzchar(password)) {
    stop("Meteomatics credentials are required.")
  }

  if (from_website) {
    location <- suppressWarnings(as.numeric(Sys.getenv(
      c("WEATHER_LATITUDE", "WEATHER_LONGITUDE", "WEATHER_BUFFER_KM")
    )))
  } else {
    if (!interactive()) stop("Run in RStudio to enter coordinates interactively.")
    location <- c(
      read_coordinate("Center latitude", -80, 84),
      read_coordinate("Center longitude", -180, 180),
      read_coordinate("Buffer from center (km)", 0.5, 5)
    )
  }

  center_lat <- location[1]
  center_lon <- location[2]
  buffer_km <- location[3]
  if (any(!is.finite(location)) || center_lat < -80 || center_lat > 84 ||
      abs(center_lon) > 180 || buffer_km < 0.5 || buffer_km > 5) {
    stop("Invalid center coordinates or buffer.")
  }

  # Use the same bounding-box calculation as ndvi_gif.py.
  delta_lat <- buffer_km / 111.32
  delta_lon <- buffer_km / (111.32 * cos(center_lat * pi / 180))
  north <- center_lat + delta_lat
  west <- center_lon - delta_lon
  south <- center_lat - delta_lat
  east <- center_lon + delta_lon

  if (south < -80 || north > 84 || west < -180 || east > 180) {
    stop("Choose an area between 80°S and 84°N that does not cross the date line.")
  }

  requested_weather_buffer <- suppressWarnings(as.numeric(
    Sys.getenv("WEATHER_REGION_BUFFER_KM", unset = as.character(buffer_km))
  ))
  if (!is.finite(requested_weather_buffer) ||
      requested_weather_buffer < buffer_km || requested_weather_buffer > 100) {
    stop("Invalid weather map buffer.")
  }
  km_per_lon_degree <- 111.32 * cos(center_lat * pi / 180)
  weather_buffer <- min(
    requested_weather_buffer,
    111.32 * min(center_lat + 80, 84 - center_lat),
    km_per_lon_degree * (180 - abs(center_lon))
  )
  weather_delta_lat <- weather_buffer / 111.32
  weather_delta_lon <- weather_buffer / km_per_lon_degree
  region <- sprintf(
    "%.8f,%.8f_%.8f,%.8f:50x50",
    center_lat + weather_delta_lat, center_lon - weather_delta_lon,
    center_lat - weather_delta_lat, center_lon + weather_delta_lon
  )
  center_label <- sprintf(
    "%.2f°%s, %.2f°%s",
    abs(center_lat), if (center_lat < 0) "S" else "N",
    abs(center_lon), if (center_lon < 0) "W" else "E"
  )

  start <- as.POSIXct(
    ceiling(as.numeric(Sys.time()) / 3600) * 3600,
    origin = "1970-01-01", tz = "UTC"
  )
  forecast_days <- 7
  step_hours <- 6
  end_times <- start + seq(step_hours, forecast_days * 24, by = step_hours) * 3600
  if (preview_only && !from_website) end_times <- tail(end_times, 1)

  fetch_grid <- function(end_time) {
    timestamp <- format(end_time, "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
    url <- paste("https://api.meteomatics.com", timestamp, "t_2m:C", region, "csv", sep = "/")
    message("Downloading forecast for ", timestamp)

    response <- request(url) |>
      req_auth_basic(trimws(username), password) |>
      req_timeout(45) |>
      req_retry(max_tries = 3) |>
      req_perform()

    lines <- strsplit(resp_body_string(response), "\\r?\\n")[[1]]
    header <- grep("^data;", lines)
    if (length(header) != 1L || header >= length(lines)) {
      stop("The API response did not contain the expected forecast grid.")
    }

    longitude <- as.numeric(strsplit(lines[header], ";", fixed = TRUE)[[1]][-1])
    grid <- read.table(
      text = paste(lines[(header + 1):length(lines)], collapse = "\n"),
      sep = ";", header = FALSE, comment.char = "", colClasses = "numeric"
    )
    if (ncol(grid) != length(longitude) + 1L || nrow(grid) < 2L ||
        length(longitude) < 2L || anyNA(longitude) || anyNA(grid[[1]])) {
      stop("The forecast grid did not have valid latitude and longitude axes.")
    }

    cells <- expand.grid(latitude = grid[[1]], longitude = longitude)
    cells$temp_c <- as.vector(as.matrix(grid[-1]))
    cells$temp_c[!is.finite(cells$temp_c) |
                 cells$temp_c %in% c(-999, -888, -777, -666)] <- NA_real_
    if (all(is.na(cells$temp_c))) stop("No usable temperature values for ", timestamp)
    cells
  }

  grids <- lapply(seq_along(end_times), function(i) fetch_grid(end_times[i]))
  all_temperatures <- unlist(lapply(grids, function(grid) grid$temp_c))
  scale_limit <- max(4, 4 * ceiling(max(abs(all_temperatures), na.rm = TRUE) / 4))

  # Space the tick labels when the full forecast spans many 4°C intervals.
  tick_step <- max(4, 4 * ceiling(scale_limit / 12))
  tick_limit <- floor(scale_limit / tick_step) * tick_step

  draw_map <- function(grid, forecast_time) {
    time_label <- format(forecast_time, "%b %d, %Y, %H:%M UTC", tz = "UTC")
    freezing_pct <- 100 * mean(grid$temp_c <= 0, na.rm = TRUE)
    temperature_range <- range(grid$temp_c, na.rm = TRUE)

    ggplot(grid, aes(longitude, latitude, fill = temp_c)) +
      geom_tile() +
      coord_fixed(ratio = 1 / cos(center_lat * pi / 180), expand = FALSE) +
      scale_fill_gradient2(
        low = "#2166ac", mid = "#f7f7f7", high = "#b35806", midpoint = 0,
        limits = c(-scale_limit, scale_limit),
        breaks = seq(-tick_limit, tick_limit, by = tick_step),
        na.value = "grey80",
        name = "Air temperature (°C)",
        guide = guide_colourbar(
          title.position = "right",
          label.position = "right",
          frame.colour = "#333333",
          ticks.colour = "#333333"
        )
      ) +
      labs(
        title = "Air Temperature Forecast",
        subtitle = sprintf(
          paste0(
            "%s | Coordinates: %s\n",
            "Weather map buffer: %g km from center\n",
            "Range: %.2f to %.2f °C at 0.002 km above ground\n",
            "%.1f%% of valid grid cells at or below freezing (0°C)\n",
            "Valid cells are map squares with a temperature forecast."
          ),
          time_label, center_label, round(weather_buffer, 1),
          temperature_range[1], temperature_range[2], freezing_pct
        )
      ) +
      theme_minimal(base_size = 12) +
      theme(
        axis.title = element_blank(), axis.text = element_blank(),
        axis.ticks = element_blank(),
        plot.title.position = "plot",
        plot.subtitle = element_text(family = "mono", size = 9),
        plot.margin = margin(6, 6, 6, 6),
        legend.position = "right",
        legend.direction = "vertical",
        legend.key.width = grid::unit(2.5, "mm"),
        legend.key.height = grid::unit(23, "mm"),
        legend.title = element_text(size = 8, angle = 90, hjust = 0.5),
        legend.text = element_text(size = 7),
        legend.margin = margin(0, 0, 0, 0),
        legend.box.spacing = grid::unit(3, "pt")
      )
  }

  output_dir <- "forecast_output"
  dir.create(output_dir, showWarnings = FALSE)
  if (!from_website) {
    first_map <- draw_map(grids[[1]], end_times[1])
    print(first_map)
    preview_path <- file.path(output_dir, "temperature_preview.png")
    ggsave(preview_path, first_map, width = 6, height = 6, dpi = 120, bg = "white")
    message("Preview saved to ", normalizePath(preview_path))
    if (preview_only) return(invisible(NULL))
  }

  frames <- character(length(end_times))
  on.exit(unlink(frames[nzchar(frames)]), add = TRUE)
  for (i in seq_along(end_times)) {
    frames[i] <- tempfile(pattern = "forecast_frame_", fileext = ".png")
    frame <- draw_map(grids[[i]], end_times[i])
    ggsave(frames[i], frame, width = 6, height = 6, dpi = 120, bg = "white")
  }

  gif_path <- file.path(output_dir, "temperature_forecast.gif")
  if (from_website) {
    animation <- magick::image_animate(magick::image_read(frames), delay = 80, loop = 0)
    magick::image_write(animation, path = gif_path, format = "gif")
  } else {
    gifski::gifski(
      frames, gif_file = gif_path,
      width = 720, height = 720, delay = 0.8, loop = TRUE
    )
  }
  message("GIF saved to ", normalizePath(gif_path))
}

build_forecast(preview_only)
