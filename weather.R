# Install once in the RStudio Console:
# install.packages(c("httr2", "ggplot2", "askpass", "gifski"))

library(httr2)
library(ggplot2)

# TRUE tests one map at day 7. FALSE exports the full 7-day GIF.
preview_only <- FALSE

build_forecast <- function(preview_only) {
  username <- trimws(Sys.getenv("METEOMATICS_USER"))
  password <- Sys.getenv("METEOMATICS_PASSWORD")
  
  if (!nzchar(username)) {
    username <- askpass::askpass("Enter your Meteomatics username")
  }
  if (!nzchar(password)) {
    password <- askpass::askpass("Enter your Meteomatics password")
  }
  if (is.null(username) || !nzchar(trimws(username)) ||
      is.null(password) || !nzchar(password)) {
    stop("Enter both Meteomatics credentials and click Source again.")
  }
  
  read_coordinate <- function(label, lower, upper) {
    repeat {
      answer <- trimws(readline(paste0(label, ": ")))
      value <- suppressWarnings(as.numeric(answer))
      
      if (is.finite(value) && value >= lower && value <= upper) {
        return(value)
      }
      
      message("Enter a number between ", lower, " and ", upper, ".")
    }
  }
  
  message("Enter the forecast bounds in decimal degrees. Use negative longitude for west.")
  
  from_website <- identical(Sys.getenv("WEATHER_WEB"), "1")
  
  if (from_website) {
    bounds <- suppressWarnings(as.numeric(Sys.getenv(
      c("WEATHER_NORTH", "WEATHER_WEST", "WEATHER_SOUTH", "WEATHER_EAST")
    )))
    
    if (any(!is.finite(bounds)) ||
        any(abs(bounds[c(1, 3)]) > 89) ||
        any(abs(bounds[c(2, 4)]) > 180)) {
      stop("Invalid forecast coordinates.")
    }
    
    north <- bounds[1]
    west  <- bounds[2]
    south <- bounds[3]
    east  <- bounds[4]
  } else {
    north <- read_coordinate("North latitude", -89, 89)
    west  <- read_coordinate("West longitude", -180, 180)
    south <- read_coordinate("South latitude", -89, 89)
    east  <- read_coordinate("East longitude", -180, 180)
  }
  
  if (north <= south || west >= east) {
    stop("North latitude must be greater than south, and west longitude must be less than east.")
  }
  
  region <- sprintf("%.5f,%.5f_%.5f,%.5f:50x50", north, west, south, east)
  
  center_lat <- (north + south) / 2
  center_lon <- (west + east) / 2
  center_label <- sprintf(
    "%.2f°%s, %.2f°%s",
    abs(center_lat), if (center_lat < 0) "S" else "N",
    abs(center_lon), if (center_lon < 0) "W" else "E"
  )
  parameter <- "t_2m:C"
  forecast_days <- 7
  step_hours <- 6
  
  # Round up to a whole UTC hour before calculating forecast times.
  start <- as.POSIXct(
    ceiling(as.numeric(Sys.time()) / 3600) * 3600,
    origin = "1970-01-01",
    tz = "UTC"
  )
  
  end_times <- start +
    seq(step_hours, forecast_days * 24, by = step_hours) * 3600
  
  if (preview_only) {
    end_times <- tail(end_times, 1)
  }
  
  fetch_grid <- function(end_time) {
    timestamp <- format(end_time, "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
    url <- paste(
      "https://api.meteomatics.com", timestamp, parameter, region, "csv",
      sep = "/"
    )
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
    
    longitude <- as.numeric(
      strsplit(lines[header], ";", fixed = TRUE)[[1]][-1]
    )
    
    grid <- read.table(
      text = paste(lines[(header + 1):length(lines)], collapse = "\n"),
      sep = ";",
      header = FALSE,
      comment.char = "",
      colClasses = "numeric"
    )
    
    if (ncol(grid) != length(longitude) + 1L ||
        nrow(grid) < 2L || length(longitude) < 2L ||
        anyNA(longitude) || anyNA(grid[[1]])) {
      stop("The forecast grid did not have valid latitude and longitude axes.")
    }
    
    # CSV rows are latitudes and columns are longitudes.
    cells <- expand.grid(latitude = grid[[1]], longitude = longitude)
    cells$temp_c <- as.vector(as.matrix(grid[-1]))
    
    reserved_values <- c(-999, -888, -777, -666)
    cells$temp_c[cells$temp_c %in% reserved_values] <- NA_real_
    
    if (all(is.na(cells$temp_c))) {
      stop("No usable temperature values for ", timestamp)
    }
    
    cells
  }
  
  grids <- lapply(seq_along(end_times), function(i) {
    fetch_grid(end_times[i])
  })
  
  # Use one color scale for every frame, with labels every 4°C.
  all_temperatures <- unlist(lapply(grids, function(grid) grid$temp_c))
  scale_limit <- max(
    4, 4 * ceiling(max(abs(all_temperatures), na.rm = TRUE) / 4)
  )
  
  draw_map <- function(grid, forecast_time) {
    local_time <- format(forecast_time, "%b %d, %Y, %H:%M UTC", tz = "UTC")
    freezing_pct <- 100 * mean(grid$temp_c <= 0, na.rm = TRUE)
    
    ggplot(grid, aes(longitude, latitude, fill = temp_c)) +
      geom_tile() +
      annotate("point", x = center_lon, y = center_lat, size = 2) +
      coord_fixed(ratio = 1 / cos(center_lat * pi / 180), expand = FALSE) +
      scale_fill_gradient2(
        low = "#2166ac",
        mid = "#f7f7f7",
        high = "#b35806",
        midpoint = 0,
        limits = c(-scale_limit, scale_limit),
        breaks = seq(-scale_limit, scale_limit, by = 4),
        na.value = "grey80",
        name = "Air temp. (°C)"
      ) +
      labs(
        title = "Air Temperature Forecast",
        subtitle = sprintf(
          paste0(
            "%s | %s\n",
            "%.1f%% of valid grid cells* at or below freezing (0°C)\n",
            "*Valid cells are map squares with a temperature forecast."
          ),
          local_time, center_label, freezing_pct
        ),
        caption = "Source: Meteomatics Weather API | Air temperature 2 m above ground"
      ) +
      theme_minimal(base_size = 12) +
      theme(
        axis.title = element_blank(),
        axis.text = element_blank(),
        axis.ticks = element_blank(),
        plot.subtitle = element_text(family = "mono"),
        plot.margin = margin(6, 6, 6, 6),
        legend.key.height = grid::unit(18, "mm"),
        legend.key.width = grid::unit(6.5, "mm"),
        legend.title = element_text(size = 12),
        legend.text = element_text(size = 10),
        legend.box.spacing = grid::unit(4, "pt")
      )
  }
  
  output_dir <- "forecast_output"
  dir.create(output_dir, showWarnings = FALSE)
  
  first_map <- draw_map(grids[[1]], end_times[1])
  print(first_map)
  
  preview_path <- file.path(output_dir, "temperature_preview.png")
  ggsave(preview_path, first_map, width = 6, height = 6, dpi = 120)
  message("Preview saved to ", normalizePath(preview_path))
  
  if (preview_only) {
    return(invisible(NULL))
  }
  
  frames <- character(length(end_times))
  on.exit(unlink(frames[nzchar(frames)]), add = TRUE)
  
  for (i in seq_along(end_times)) {
    frames[i] <- tempfile(pattern = "michigan_frame_", fileext = ".png")
    frame <- draw_map(grids[[i]], end_times[i])
    ggsave(frames[i], frame, width = 6, height = 6, dpi = 120)
  }
  
  gif_path <- file.path(output_dir, "temperature_forecast.gif")
  if (from_website) {
    animation <- magick::image_animate(
      magick::image_read(frames), delay = 80, loop = 0
    )
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