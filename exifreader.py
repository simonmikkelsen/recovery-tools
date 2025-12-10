from datetime import datetime
import re

from importt.timezoneutil import TimeZoneUtil
import cv2

""" Take data for a single image from exiftool and extract information, trying to take
    the best available data from the EXIF data no matter what and how the individual camera
    has saved the data.
"""
class ExifReader:
  exiftime_to_normal_time_regex = re.compile(r'^(\d{4}):(\d{2}):(\d{2})')
  space_padded_timestamp_regex = re.compile(r'^(\d{4})-\s?(\d{1,2})-\s?(\d{1,2})\s+(\d{1,2}):\s?(\d{1,2}):\s?(\d{1,2})$')

  # Match both 2023-09-07_03-23-43.jpg and IMG_20150403_155315.jpg
  # Also       2014-07-03_19-06-07_00035.MTS
  # Also       Screenshot_20170130-192629.png
  # Also       R0010020_20160628152348_er.MP4
  # Also       2022-07-24-172658882.mp4
  filename_without_timezone = re.compile(r'[^0-9]*([12][09]\d{2})[_./-]?(\d{2})[_./-]?(\d{2})[_./-]?(\d{2})[_./-]?(\d{2})[_./-]?(\d{2})[-:_\.]?.*\.')
  #Match: 00191_2022-10-20T121817+0200.jpg
  filename_with_timezone = re.compile(r'[^0-9]*([12][09]\d{2})[_./-]?(\d{2})[_./-]?(\d{2})T(\d{2})(\d{2})(\d{2})(\+\d{4}).*\.')

  def __init__(self, exif_data:dict, timezoneutil:TimeZoneUtil):
    self.exif_data = exif_data
    self.tz = timezoneutil
      
  def get_altitude(self) -> str|None:
    altitude = self.exif_data.get('EXIF:GPSAltitude', None) or self.exif_data.get('Composite:GPSAltitude', None) \
            or self.exif_data.get('EXIF:Altitude', None) or self.exif_data.get('Composite:Altitude', None)
      
    if not altitude:
      return None

    try:
      # Fails if altitude is not a number
      float(altitude)
      return altitude
    except ValueError:
      return None

  def get_sourcefile(self) -> str:
    return self.exif_data.get('SourceFile', None)
  
  def extract_video_duration(self) -> str|None:
    duration = self.__extract_video_duration_from_exif()
    if duration:
      return duration
    return self.__extract_video_duration_slow()
  
  def __extract_video_duration_from_exif(self) -> str|None:
    duration = self.exif_data.get('EXIF:Duration', None) or self.exif_data.get('Composite:Duration', None) \
      or self.exif_data.get('Media:Duration', None) or self.exif_data.get('Track:Duration', None)
    
    if not duration:
      return None

    try:
      # Fails if duration is not a number
      float(duration)
      return duration
    except ValueError:
      return None
  
  def __get_video_length_cv2(self, source_file):
    cap = cv2.VideoCapture(source_file)
    if not cap.isOpened():
      return None
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else None
    cap.release()
    return duration

  def __extract_video_duration_slow(self):
    source_file = self.get_sourcefile()
    if not source_file:
      return None
    
    duration = self.__get_video_length_cv2(source_file)
    if not duration:
      return None
    
    try:
      return int(duration)
    except ValueError:
      return None
    except TypeError:
      return None
  
  def extract_gps_coordinates(self) -> tuple[str, str]:
    gps_position = self.exif_data.get('Composite:GPSPosition', {})
    
    latitude = None
    longitude = None
    if gps_position:
      # Get latitude and longitude from GPSPosition
      gps_position = gps_position.split(' ')
      if len(gps_position) == 2:
        try:
          latitude = float(gps_position[0])
          longitude = float(gps_position[1])
        except ValueError:
          pass

    # First method did not work: Try another.
    if not latitude or not longitude:
      latitude = self.exif_data.get('EXIF:GPSLatitude', None)
      longitude = self.exif_data.get('EXIF:GPSLongitude', None)
      # Correct with EXIF:GPSLatitudeRef and EXIF:GPSLongitudeRef
      if latitude and longitude:
        latitude_ref = self.exif_data.get('EXIF:GPSLatitudeRef', 'N')
        longitude_ref = self.exif_data.get('EXIF:GPSLongitudeRef', 'E')
        if latitude_ref and longitude_ref:
          if latitude_ref[0].upper() == 'S':
            latitude = -latitude
          if longitude_ref[0].upper() == 'W':
            longitude = -longitude
    return latitude, longitude

  def __sanitize_exif_timestamp(self, timestamp:str) -> str:
    if not timestamp:
      return None
    if '0000:00:00 00:00:00' in timestamp:
      return None

    # Match: 2018- 9-18 12: 1: 0
    # Some cameras, like Ricoh Theta V, will use spaces instead of 0 before single digits.
    match = ExifReader.space_padded_timestamp_regex.match(timestamp)
    if match:
      # Make exif style timstamp with : between date and time.
      timestamp = f"{match.group(1)}:{match.group(2).zfill(2)}:{match.group(3).zfill(2)} {match.group(4).zfill(2)}:{match.group(5).zfill(2)}:{match.group(6).zfill(2)}"
    
    return timestamp

  def extract_time(self, lat, lon) -> str:
    exif_data = self.exif_data

    msg = []
    point_time = exif_data.get('EXIF:DateTimeOriginal') or exif_data.get('EXIF:DateTime') or exif_data.get('EXIF:CreateDate') \
      or exif_data.get('QuickTime:CreateDate') or exif_data.get('QuickTime:TrackCreateDate') or exif_data.get('QuickTime:ContentCreateDate')
    point_time = self.__sanitize_exif_timestamp(point_time)
    #ExifIFD:DateTimeOriginal or ExifIFD:CreateDate 
    msg.append(f"DateTimeOriginal: {point_time}")
    
    if not point_time:
      point_time = self.__extract_from_subsec_createdate(exif_data, msg)
    
    if not point_time:
      gps_date_time = exif_data.get('EXIF:GPSDateTime') or exif_data.get('Composite:GPSDateTime') \
        or exif_data.get('EXIF:GpsDateTime') or exif_data.get('Composite:GpsDateTime')
      msg.append(f"- GPSDateTime: {gps_date_time}")

      gps_date_time_obj = self.tz.utc_to_local_time(gps_date_time, lat=lat, lon=lon)
      msg.append(f"- GPSDateTime Obj: {gps_date_time_obj}")
        
      if self.validateDateTimeObj(gps_date_time_obj, "loc1"):
        point_time = gps_date_time_obj.strftime('%Y:%m:%d %H:%M:%S %Z')
        msg.append(f"- Val:idated point time: {point_time}")
      else:
        msg.append(f"- GPSDateTime not valid: {gps_date_time}")

    if not point_time:
      gps_date_stamp = exif_data.get('EXIF:GPSDateStamp') or exif_data.get('EXIF:GpsDateStamp')
      gps_time_stamp = exif_data.get('EXIF:GPSDateStamp') or exif_data.get('EXIF:GpsTimeStamp')
      msg.append(f"- GPSDateStamp: {gps_date_stamp} and time stamp: {gps_time_stamp}")
      if gps_date_stamp and gps_time_stamp:
        gps_date_obj = datetime.strptime(gps_date_stamp, '%Y:%m:%d')
        if self.validateDateTimeObj(gps_date_obj, "loc2"):
          # Filter out cases where GPS time is not retrieved and the clock just starts at 1970.
          gps_date_time_obj = self.tz.utc_to_local_time(f"{gps_date_stamp} {gps_time_stamp}", lat=lat, lon=lon)
          # If gps_date_time_obj is not a datetime print a warning
          if not isinstance(gps_date_time_obj, datetime):
            print(f"Warning: String should be a date time {str(gps_date_time_obj)} for file: {self.get_sourcefile()}")
          point_time = gps_date_time_obj.strftime('%Y:%m:%d %H:%M:%S %Z')
          msg.append(f"- Validated point time: {point_time}")
        else:
          msg.append(f"- GPSDateStamp not valid: {gps_date_stamp}")
    
    if not point_time:
      # Try to get the time from the file name if named e.g. IMG_20150403_155315.jpg
      filename = self.get_sourcefile()
      msg.append(f"- Get from filename: {filename}")
      #TODO: Do something about the huge amount of references to match groups.
      if filename:
        match = ExifReader.filename_without_timezone.match(filename)
        if match and self.validateDateTime(match.group(1), match.group(2), match.group(3), match.group(4), match.group(5), match.group(6)):
          point_time = f"{match.group(1)}:{match.group(2)}:{match.group(3)} {match.group(4)}:{match.group(5)}:{match.group(6)}"
          timezone = self.tz.get_local_tzinfo(lat=lat, lon=lon)
            # TODO: Handle unknown timezone
          if timezone:
            point_time += f" {timezone}" or ""
          msg.append(f"- Validated point time1: {point_time}")
        if not point_time:
          match = ExifReader.filename_with_timezone.match(filename)
          if match and self.validateDateTime(match.group(1), match.group(2), match.group(3), match.group(4), match.group(5), match.group(6)):
            point_time = f"{match.group(1)}:{match.group(2)}:{match.group(3)} {match.group(4)}:{match.group(5)}:{match.group(6)}"
            utc_offset = match.group(7)
            timezone = self.tz.get_tzinfo_from_utc_offset(utc_offset)
            if timezone:
              point_time += f" {timezone}" or ""
            msg.append(f"- Validated point time2: {point_time}")
        if not point_time:
          msg.append(f"- Filename does not contain valid time: {filename}")

    if not point_time:
      # We give up: Leave it to the caller to use another library to create an uncertain time.
      return None

    # In exif dates are separated by : but in datetime they are separated by -    
    # If timestamp has format yyyy:mm:dd HH:MM:SS, convert it to yyyy-mm-dd HH:MM:SS
    point_time = ExifReader.exiftime_to_normal_time_regex.sub(r'\1-\2-\3', point_time)
    
    return point_time

  def __extract_from_subsec_createdate(self, exif_data, msg):
      subsectime = exif_data.get('Composite:SubSecCreateDate')
      # or SubSecDateTimeOriginal
      msg.append(f"- SubSecCreateDate: {subsectime}")
      # Format is e.g. 2014:12:06 10:04:20.426273 remove the last part
      if subsectime and subsectime.count('.') > 0:
        point_time = subsectime.split('.')[0]
        msg.append(f"- SubSecCreateDate: {point_time}")
        return point_time
      return None

  def validateDateTimeObj(self, datetime_obj: datetime, location:str="") -> bool:
    if not datetime_obj:
      # This is not an error: Just an object we cannot use.
      return
    if not isinstance(datetime_obj, datetime):
      # TODO: Revisit
      print(f"validateDateTimeObj: Not a datetime object: {str(datetime_obj)} ({location})")
      return False
    return datetime_obj and self.validateDateTime(
      datetime_obj.year, datetime_obj.month, datetime_obj.day,
      datetime_obj.hour, datetime_obj.minute, datetime_obj.second)
  
  def validateDateTime(self, year, month, day, hour, minute, second):
    if int(year) < 1900 or int(year) > datetime.now().year:
      return False
    if int(month) < 1 or int(month) > 12:
      return False
    if int(day) < 1 or int(day) > 31:
      return False
    if int(hour) < 0 or int(hour) > 23:
      return False
    if int(minute) < 0 or int(minute) > 59:
      return False
    if int(second) < 0 or int(second) > 59:
      return False
    
    # If close to 1970.01.01, it is probably a bad date, because a GPS date is not available but the clock starts at 1970.
    if int(year) < 1975 and int(month) == 1 and int(day) == 1:
      return False
    
    return True

if __name__ == '__main__':
  filenames = ['IMG_20150403_155315.jpg', '2023-09-07_03-23-43.jpg']
  for filename in filenames:
    match = re.search(r'[^0-9]*(\d{4})[_./-]?(\d{2})[_./-]?(\d{2})[_./-]?(\d{2})[_./-]?(\d{2})[_./-]?(\d{2})\.', filename)
    if match:
      point_time = f"{match.group(1)}:{match.group(2)}:{match.group(3)} {match.group(4)}:{match.group(5)}:{match.group(6)}"
      print (point_time)
      print (ExifReader.validateDateTime(2023, 9, 7, 3, 23, 43))
      print (ExifReader.validateDateTime(2023, 9, 7, 3, 23, 61))
      
