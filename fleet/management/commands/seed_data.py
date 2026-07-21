"""
Generates synthetic data for the ZNPHI Fleet Manager prototype.

Run with:   python manage.py seed_data
Clean with: python manage.py flush_seed

All seed user accounts use the SEED_PREFIX convention so flush_seed can
identify and remove them without touching real user accounts.

Date rationale: data covers March–June 2026 to align with the prototype
period described in the construction guide.
"""
import datetime
import random

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction

from bookings.models import Department, District, Province, TransportRequest, TripAssignment
from fleet.models import Driver, FuelRecord, MaintenanceRecord, Vehicle

User = get_user_model()

SEED_PREFIX = 'seed_'

# ── Vehicle data ───────────────────────────────────────────────────────────────
# Columns: vehicle_type, year, fuel_type, seating_capacity, current_mileage,
#          maintenance_target ('green'|'amber'|'red'), status
VEHICLE_SPECS = [
    # Toyota Hilux (12) — pickup
    ('Hilux', 2022, 'Diesel', 5,  35_000, 'green',  'Available'),
    ('Hilux', 2021, 'Diesel', 5,  42_000, 'green',  'Available'),
    ('Hilux', 2020, 'Diesel', 5,  58_000, 'green',  'Available'),
    ('Hilux', 2019, 'Diesel', 5,  75_000, 'green',  'Available'),
    ('Hilux', 2023, 'Diesel', 5,  28_000, 'green',  'Available'),
    ('Hilux', 2018, 'Diesel', 5,  97_000, 'amber',  'Available'),
    ('Hilux', 2020, 'Diesel', 5,  63_000, 'green',  'Available'),
    ('Hilux', 2017, 'Diesel', 5, 114_000, 'amber',  'Available'),
    ('Hilux', 2022, 'Diesel', 5,  47_000, 'green',  'Available'),
    ('Hilux', 2019, 'Diesel', 5,  82_000, 'green',  'Available'),
    ('Hilux', 2021, 'Petrol', 5,  54_000, 'red',    'Available'),
    ('Hilux', 2016, 'Diesel', 5, 138_000, 'green',  'Emergency Standby'),
    # Toyota Land Cruiser (11) — SUV
    ('Land Cruiser', 2022, 'Diesel', 7,  40_000, 'green',  'Available'),
    ('Land Cruiser', 2020, 'Diesel', 7,  68_000, 'green',  'Available'),
    ('Land Cruiser', 2019, 'Diesel', 7,  91_000, 'amber',  'Available'),
    ('Land Cruiser', 2018, 'Diesel', 7, 108_000, 'green',  'Available'),
    ('Land Cruiser', 2021, 'Diesel', 7,  55_000, 'green',  'Available'),
    ('Land Cruiser', 2017, 'Diesel', 7, 131_000, 'red',    'Available'),
    ('Land Cruiser', 2023, 'Diesel', 7,  22_000, 'green',  'Available'),
    ('Land Cruiser', 2020, 'Diesel', 7,  73_000, 'green',  'Available'),
    ('Land Cruiser', 2016, 'Diesel', 7, 165_000, 'green',  'Emergency Standby'),
    ('Land Cruiser', 2019, 'Diesel', 7,  95_000, 'green',  'Available'),
    ('Land Cruiser', 2021, 'Diesel', 7,  48_000, 'green',  'Emergency Standby'),
]

LICENSE_PLATES = [
    'BAA 4271', 'BAB 1893', 'BAC 5604', 'BAD 3217', 'BAE 7832',
    'BAF 2156', 'BAG 9043', 'BAH 6785', 'BAJ 3421', 'BAK 8097',
    'BAL 5263', 'BAM 1748', 'BAN 4592', 'BAP 7136', 'BAQ 2864',
    'BAR 9451', 'BAS 6073', 'BAT 3892', 'BAU 1547', 'BAV 8236',
    'BAW 4918', 'BAX 7653', 'BAY 2391',
]

# ── Driver data ────────────────────────────────────────────────────────────────
# 20 drivers as per construction guide spec; drivers 7 and 14 are on leave.
DRIVER_SPECS = [
    (f'Driver {i}', 'On Leave' if i in (7, 14) else 'Available')
    for i in range(1, 21)
]

# ── Seed requester accounts ────────────────────────────────────────────────────
# Columns: username, first_name, last_name, position
REQUESTER_DATA = [
    ('seed_staff_1', 'ZNPHI Staff', '1', 'Surveillance Officer'),
    ('seed_staff_2', 'ZNPHI Staff', '2', 'Field Epidemiologist'),
    ('seed_staff_3', 'ZNPHI Staff', '3', 'Public Health Specialist'),
    ('seed_staff_4', 'ZNPHI Staff', '4', 'Laboratory Technician'),
    ('seed_staff_5', 'ZNPHI Staff', '5', 'Disease Intelligence Analyst'),
    ('seed_staff_6', 'ZNPHI Staff', '6', 'Programme Officer'),
    ('seed_staff_7', 'ZNPHI Staff', '7', 'Emergency Response Coordinator'),
    ('seed_staff_8', 'ZNPHI Staff', '8', 'Health Policy Advisor'),
]

# ── Transport request content ──────────────────────────────────────────────────
PROGRAMME_ACTIVITIES = [
    'Disease surveillance field visit',
    'District health review meeting',
    'Community health education outreach',
    'Outbreak investigation — suspected cholera',
    'Routine immunisation monitoring',
    'HIV/TB case finding and contact tracing',
    'Environmental health assessment',
    'Laboratory sample collection and transport',
    'Emergency preparedness planning workshop',
    'Maternal and child health supervision visit',
    'Vector control spray programme supervision',
    'Cross-border disease surveillance',
    'Health facility assessment',
    'DHIS2 data review and capacity building',
]

DESTINATIONS = [
    'District Health Office',
    'District Hospital',
    'Urban Health Centre',
    'Community Health Post',
    'Rural Health Centre',
    'Provincial Health Office',
    'ZNPHI Field Station',
]

REJECTION_COMMENTS = [
    'No vehicles available for the requested period. Please resubmit for an alternative date.',
    'Request submitted after the operational cutoff for this week. Please plan ahead.',
    'Programme activity overlaps with an existing approved trip to the same district — please coordinate.',
    'Insufficient justification for emergency classification. Please resubmit as a standard request.',
]

COORDINATION_NOTES = [
    'Our team is collecting samples from a separate facility in the same district.',
    'We have a morning session at the District Hospital; the other team is based at the Urban Health Centre.',
    'Our activities are scheduled on different days within the same week.',
    'Different programme areas — no practical way to consolidate vehicles.',
]

# ── Fuel data ──────────────────────────────────────────────────────────────────
FUEL_LOCATIONS = [
    'Lusaka — Great East Road', 'Livingstone — Mosi-oa-Tunya Rd',
    'Ndola — Broadway', 'Kitwe — Freedom Avenue', 'Kabwe — Cairo Road',
    'Chipata — Chipata Urban', 'Monze — Monze Boma', 'Kafue — Kafue Town',
    'Mazabuka — Mazabuka Town', 'Choma — Choma Central',
]

# ── Maintenance data ───────────────────────────────────────────────────────────
MAINTENANCE_SERVICE_TYPES = [
    'Full service — oil, filters, belts',
    'Oil and filter change',
    'Full service — oil, air filter, spark plugs',
    'Oil change and safety inspection',
    'Scheduled 10,000 km service',
    'Scheduled 15,000 km service',
]

MAINTENANCE_VENDORS = [
    'CFAO Motors Zambia, Lusaka', 'Toyota Zambia, Lusaka',
    'Toyota Zambia, Ndola', 'Associated Motors, Kitwe',
    'Autoworld, Lusaka', 'Premier Auto, Livingstone',
]

# ── Date windows ───────────────────────────────────────────────────────────────
SEED_START  = datetime.date(2026, 3, 2)
SEED_END    = datetime.date(2026, 6, 21)   # last date we generate requests from
SEED_TODAY  = datetime.date(2026, 6, 22)   # "now" for the seed data world
SPIKE_WEEK  = datetime.date(2026, 4, 6)    # Mon of the ~50-request spike week

# Districts used for coordination nudge demo clusters.
# Each tuple: (province_name, district_name, week_monday)
NUDGE_CLUSTERS = [
    ('Lusaka',   'Lusaka',      datetime.date(2026, 3, 16)),
    ('Southern', 'Livingstone', datetime.date(2026, 4, 13)),
    ('Eastern',  'Chipata',     datetime.date(2026, 5, 18)),
]


class Command(BaseCommand):
    help = 'Populate the database with synthetic data for development and demonstration.'

    def handle(self, *args, **options):
        if not Department.objects.exists():
            self.stdout.write(self.style.ERROR(
                'No departments found. Load fixtures first:\n'
                '  python manage.py loaddata departments provinces_districts'
            ))
            return

        if Vehicle.objects.exists():
            self.stdout.write(self.style.WARNING(
                'Vehicles already exist. Run flush_seed first if you want a clean reload.'
            ))
            return

        self.stdout.write('Seeding database…')
        rng = random.Random(42)

        with transaction.atomic():
            drivers  = self._seed_drivers(rng)
            vehicles = self._seed_vehicles()
            self._seed_maintenance_records(vehicles, rng)
            self._seed_fuel_records(vehicles, rng)
            users    = self._seed_users()
            requests = self._seed_transport_requests(users, rng)
            self._seed_trip_assignments(requests, vehicles, drivers, rng)

        self.stdout.write(self.style.SUCCESS(
            f'\nDone — {Vehicle.objects.count()} vehicles, '
            f'{Driver.objects.count()} drivers, '
            f'{TransportRequest.objects.count()} requests, '
            f'{TripAssignment.objects.count()} assignments, '
            f'{FuelRecord.objects.count()} fuel records, '
            f'{MaintenanceRecord.objects.count()} maintenance records.'
        ))

        # SEED_TODAY is anchored to a fixed date; real-today may be later.
        # Apply date-based status transitions immediately so the DB reflects
        # the correct state whenever seed_data is run.
        self.stdout.write('Applying status transitions for real-today…')
        call_command('run_transitions')

    # ── Drivers ───────────────────────────────────────────────────────────────

    def _seed_drivers(self, rng):
        drivers = [
            Driver.objects.create(
                name=name,
                phone=f'+260 970 000 {i:03d}',
                status=status,
            )
            for i, (name, status) in enumerate(DRIVER_SPECS)
        ]
        self.stdout.write(f'  {len(drivers)} drivers')
        return drivers

    # ── Vehicles ──────────────────────────────────────────────────────────────

    def _seed_vehicles(self):
        vehicles = []
        for i, (vtype, year, fuel, seats, mileage, maint_target, status) in enumerate(VEHICLE_SPECS):
            v = Vehicle.objects.create(
                make='Toyota',
                model=vtype,
                year=year,
                license_plate=LICENSE_PLATES[i],
                vehicle_type=vtype,
                current_mileage=mileage,
                seating_capacity=seats,
                fuel_type=fuel,
                status=status,
                maintenance_interval_km=5000,
                # last_service_mileage / last_service_date are set by the
                # post_save signal on MaintenanceRecord (see _seed_maintenance_records).
            )
            vehicles.append((v, maint_target))
        self.stdout.write(f'  {len(vehicles)} vehicles')
        return vehicles

    # ── Maintenance records ───────────────────────────────────────────────────

    def _seed_maintenance_records(self, vehicles_with_targets, rng):
        """Create 2–4 historical service records per vehicle.

        The most-recent record (by date) determines each vehicle's maintenance
        baseline via the post_save signal on MaintenanceRecord.  We choose
        mileage_at_service so the resulting km_until_service matches the
        intended 'green' / 'amber' / 'red' target.

        Thresholds from Vehicle.maintenance_status:
          green  → km_until_service > 500
          amber  → 0 <= km_until_service <= 500
          red    → km_until_service < 0
        """
        records_created = 0

        for vehicle, maint_target in vehicles_with_targets:
            mileage = vehicle.current_mileage

            # mileage_at_service for the most-recent (baseline) service record.
            if maint_target == 'green':
                # e.g. 2 500 km remaining → comfortably in green
                baseline_service_mileage = mileage - rng.randint(1_500, 3_000)
            elif maint_target == 'amber':
                # e.g. ~300 km remaining → within 500 km threshold
                baseline_service_mileage = mileage - rng.randint(4_600, 4_900)
            else:  # red — overdue
                baseline_service_mileage = mileage - rng.randint(5_200, 6_500)

            # 1–3 older historical records created before the baseline.
            num_history = rng.randint(1, 3)
            history_mileage = baseline_service_mileage
            history_date    = SEED_TODAY - datetime.timedelta(days=rng.randint(90, 180))

            for _ in range(num_history):
                history_mileage -= rng.randint(4_800, 5_500)
                history_date    -= datetime.timedelta(days=rng.randint(60, 90))
                MaintenanceRecord.objects.create(
                    vehicle=vehicle,
                    date=history_date,
                    mileage_at_service=max(history_mileage, 5_000),
                    service_type=rng.choice(MAINTENANCE_SERVICE_TYPES),
                    cost=rng.randint(1_200, 4_500),
                    vendor=rng.choice(MAINTENANCE_VENDORS),
                )
                records_created += 1

            # The most-recent service — the signal sets last_service_mileage to this.
            baseline_date = SEED_TODAY - datetime.timedelta(days=rng.randint(14, 75))
            MaintenanceRecord.objects.create(
                vehicle=vehicle,
                date=baseline_date,
                mileage_at_service=baseline_service_mileage,
                service_type=rng.choice(MAINTENANCE_SERVICE_TYPES),
                cost=rng.randint(1_200, 4_500),
                vendor=rng.choice(MAINTENANCE_VENDORS),
            )
            records_created += 1

        self.stdout.write(f'  {records_created} maintenance records')

    # ── Fuel records ──────────────────────────────────────────────────────────

    def _seed_fuel_records(self, vehicles_with_targets, rng):
        fuel_start = datetime.date(2026, 3, 1)
        fuel_end   = datetime.date(2026, 6, 20)
        span_days  = (fuel_end - fuel_start).days
        records_created = 0

        for vehicle, _ in vehicles_with_targets:
            num_fillups = rng.randint(4, 8)
            interval    = span_days // num_fillups
            mileage     = max(vehicle.current_mileage - rng.randint(8_000, 20_000), 15_000)

            for i in range(num_fillups):
                offset      = i * interval + rng.randint(0, max(interval - 5, 1))
                fillup_date = fuel_start + datetime.timedelta(days=offset)
                liters      = round(rng.uniform(40.0, 75.0), 2)
                cpp         = round(rng.uniform(27.50, 30.00), 2)
                mileage    += rng.randint(800, 2_500)

                FuelRecord.objects.create(
                    vehicle=vehicle,
                    date=fillup_date,
                    liters=liters,
                    cost_per_liter=cpp,
                    total_cost=round(liters * cpp, 2),
                    location=rng.choice(FUEL_LOCATIONS),
                    mileage_at_fillup=mileage,
                )
                records_created += 1

        self.stdout.write(f'  {records_created} fuel records')

    # ── Seed users ────────────────────────────────────────────────────────────

    def _seed_users(self):
        requester_group = Group.objects.get(name='Requester')
        users = []
        for username, first, last, position in REQUESTER_DATA:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first,
                    'last_name':  last,
                    'email':      f'{username}@znphi.gov.zm',
                },
            )
            user.groups.set([requester_group])
            users.append((user, f'{first} {last}', position))
        self.stdout.write(f'  {len(users)} seed requester accounts')
        return users

    # ── Transport requests ────────────────────────────────────────────────────

    def _seed_transport_requests(self, users, rng):
        departments = list(Department.objects.all())

        # Build a dict: province_name → {'province': obj, 'districts': [obj, ...]}
        province_map = {}
        for prov in Province.objects.prefetch_related('districts').all():
            districts = list(prov.districts.all())
            if districts:
                province_map[prov.name] = {'province': prov, 'districts': districts}
        all_prov_names = list(province_map.keys())

        requests = []

        def _status_for_date(period_from, period_to):
            """Return a realistic status based on where the trip falls relative to SEED_TODAY."""
            # Future: not yet started.
            if period_from > SEED_TODAY:
                # Far-future requests sit in the approval queue; near-future ones are confirmed.
                return 'Submitted' if period_from > datetime.date(2026, 7, 5) else 'Approved'

            # Currently active: started on or before today, ends today or later.
            if period_to >= SEED_TODAY:
                return 'In Progress'

            # Past: trip has fully ended — mostly completed, small rejection/cancellation rate.
            r = rng.random()
            if r < 0.08:
                return 'Rejected'
            if r < 0.13:
                return 'Cancelled'
            return 'Completed'

        def _make_request(period_from, period_to, status,
                          user_entry, prov_name=None, dist_name=None,
                          is_emergency=False, is_cluster=False):
            """Create one TransportRequest; patch date_of_request via queryset
            to work around auto_now_add preventing direct assignment."""
            if prov_name and prov_name in province_map:
                prov_data = province_map[prov_name]
                province  = prov_data['province']
                district  = next(
                    (d for d in prov_data['districts'] if d.name == dist_name),
                    rng.choice(prov_data['districts']),
                ) if dist_name else rng.choice(prov_data['districts'])
            else:
                chosen    = rng.choice(all_prov_names)
                prov_data = province_map[chosen]
                province  = prov_data['province']
                district  = rng.choice(prov_data['districts'])

            user_obj, display_name, position = user_entry
            dept  = rng.choice(departments)
            num_v = 3 if rng.random() < 0.02 else (2 if rng.random() < 0.08 else 1)

            # Submitted requests are recent; historical ones were submitted
            # 14–45 days before the trip start, with ~12% being late bookings
            # (< 14 days lead time).
            if status == 'Submitted':
                request_date = SEED_TODAY - datetime.timedelta(days=rng.randint(0, 7))
            elif rng.random() < 0.12:
                # Late booking — submitted less than 2 weeks before trip
                request_date = period_from - datetime.timedelta(days=rng.randint(3, 13))
            else:
                request_date = period_from - datetime.timedelta(days=rng.randint(14, 45))

            # Clusters: requester acknowledges the nudge and adds a note.
            acknowledged = is_cluster or (
                status not in ('Submitted', 'Rejected', 'Cancelled') and rng.random() < 0.15
            )
            coord_note = rng.choice(COORDINATION_NOTES) if acknowledged else ''

            approved_date = None
            if status in ('Approved', 'In Progress', 'Completed'):
                approved_date = request_date + datetime.timedelta(days=rng.randint(1, 5))

            admin_comment = rng.choice(REJECTION_COMMENTS) if status == 'Rejected' else ''

            tr = TransportRequest.objects.create(
                requester_name=display_name,
                department=dept,
                position=position,
                programme_activity=rng.choice(PROGRAMME_ACTIVITIES),
                period_from=period_from,
                period_to=period_to,
                province=province,
                district=district,
                destination=rng.choice(DESTINATIONS),
                num_vehicles=num_v,
                num_drivers=num_v,
                num_passengers=rng.randint(2, 8),
                is_emergency=is_emergency,
                status=status,
                admin_comment=admin_comment,
                coordination_acknowledged=acknowledged,
                coordination_note=coord_note,
                approved_date=approved_date,
                submitted_by=user_obj,
            )
            # Override the auto_now_add date with the historically correct value.
            TransportRequest.objects.filter(pk=tr.pk).update(date_of_request=request_date)
            return tr

        # ── Regular daily requests (Mon–Fri) ──────────────────────────────────
        current = SEED_START
        while current <= SEED_END:
            if current.weekday() < 5:   # Monday–Friday only
                is_spike   = SPIKE_WEEK <= current < SPIKE_WEEK + datetime.timedelta(days=5)
                daily_count = rng.randint(9, 13) if is_spike else rng.randint(2, 4)
                for _ in range(daily_count):
                    period_from = current + datetime.timedelta(days=rng.randint(3, 21))
                    period_to   = period_from + datetime.timedelta(days=rng.randint(1, 5))
                    status      = _status_for_date(period_from, period_to)
                    is_emerg    = rng.random() < 0.08
                    requests.append(
                        _make_request(period_from, period_to, status,
                                      rng.choice(users), is_emergency=is_emerg)
                    )
            current += datetime.timedelta(days=1)

        # ── Coordination nudge clusters ───────────────────────────────────────
        # Five overlapping trips to the same district in the same week trigger
        # the nudge for any subsequent request to that district+window.
        for prov_name, dist_name, week_start in NUDGE_CLUSTERS:
            for _ in range(5):
                day_offset  = rng.randint(0, 4)     # Mon–Fri of that week
                period_from = week_start + datetime.timedelta(days=day_offset)
                period_to   = period_from + datetime.timedelta(days=rng.randint(1, 3))
                status      = _status_for_date(period_from, period_to)
                requests.append(
                    _make_request(period_from, period_to, status,
                                  rng.choice(users), prov_name=prov_name,
                                  dist_name=dist_name, is_cluster=True)
                )

        # ── Future-dated submitted batch (demo approval queue) ────────────────
        future_start = datetime.date(2026, 6, 29)
        for _ in range(20):
            period_from = future_start + datetime.timedelta(days=rng.randint(0, 21))
            period_to   = period_from + datetime.timedelta(days=rng.randint(1, 5))
            requests.append(
                _make_request(period_from, period_to, 'Submitted', rng.choice(users))
            )

        self.stdout.write(f'  {len(requests)} transport requests')
        return requests

    # ── Trip assignments ──────────────────────────────────────────────────────

    def _seed_trip_assignments(self, requests, vehicles_with_targets, drivers, rng):
        """Assign vehicles and drivers to all non-cancelled, non-rejected,
        non-submitted requests.  Cycles through the fleet evenly so every
        vehicle accumulates a realistic trip history."""
        assignable = {'Approved', 'In Progress', 'Completed'}

        # Emergency standby vehicles are dedicated reserves; exclude from
        # regular trip assignments to keep the demo data realistic.
        trip_vehicles = [v for v, _ in vehicles_with_targets if v.status != 'Emergency Standby']
        trip_drivers  = [d for d in drivers if d.status != 'On Leave']

        v_idx = d_idx = 0
        count = 0

        for tr in requests:
            if tr.status not in assignable:
                continue
            for _ in range(tr.num_vehicles):
                TripAssignment.objects.create(
                    transport_request=tr,
                    vehicle=trip_vehicles[v_idx % len(trip_vehicles)],
                    driver=trip_drivers[d_idx % len(trip_drivers)],
                )
                v_idx += 1
                d_idx += 1
                count += 1

        self.stdout.write(f'  {count} trip assignments')
