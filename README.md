# travel_api
## Example run:1
python flight_search.py \
  --from LHR LGW STN LTN BHX \
  --to EVN \
  --depart-start 2025-06-04 --depart-end 2025-06-10 \
  --max-stay 3-6 \
  --filter-depart-days-time Tue Wed Thu Fri "Sat(00:00-08:00)" \
  --filter-return-days-time Sat Sun Mon Tue \
  --max-departure-stopover 10 7 \
  --max-return-stopover 8 \
  --sort-by price duration \
  --max-results 15

## Example run:2
python flight_search.py --from LHR LGW STN LTN BHX --to EVN --depart 2025-06-04 --return 2025-06-10 --sort-by price --max-results 5 \
  --max-departure-stopover 10 7 \
  --max-return-stopover 8
